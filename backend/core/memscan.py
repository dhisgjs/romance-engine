# -*- coding: utf-8 -*-
"""从微信 4.x (Weixin.exe) 进程内存中扫描数据库密钥。

原理：微信 4.x 用 WCDB(SQLCipher) 加密本地数据库，运行时密钥以
ASCII 形式留在进程内存里，格式为 x'<64位hex密钥><32位hex盐>'，
即 96 个连续 hex 字符（key 64 + salt 32）。用数据库文件第一页前
16 字节的 salt 做匹配，即可确认哪段内存对应哪个库。
本模块只读进程内存，不写入、不注入、不调用微信任何接口。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import re
from dataclasses import dataclass, field

# ---- 常量 ----
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
MAX_REGION = 512 * 1024 * 1024  # 跳过异常大的区域
CHUNK = 2 * 1024 * 1024         # 每次读取 2MB（稳定；8MB 大块读会漏扫部分区域）
OVERLAP = 256                    # 相邻块重叠，避免模式跨界被截断

_IS_WIN = os.name == "nt"
if _IS_WIN:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:
    # 非 Windows（部署在服务器上只做解密/浏览，不做内存扫描）
    kernel32 = None


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64),
        ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wt.DWORD),
        ("_pad1", wt.DWORD),
        ("RegionSize", ctypes.c_uint64),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
        ("_pad2", wt.DWORD),
    ]


# 兼容三种缓存形态：x'96hex'(key+salt)、x'64hex'(仅 key)、裸 96hex（4.1+）
_HEX_PAT = re.compile(
    rb"x'([0-9a-fA-F]{64,192})'"
    rb"|(?<![0-9a-fA-F])([0-9a-fA-F]{96})(?![0-9a-fA-F])"
)
MAX_BARE_KEYS = 5000  # 仅 key 的候选上限，防止内存膨胀

# 4.1+：passphrase 以 libc++ std::string 形式存在（指针 + size=32 + capacity≈0x2f）
# 匹配 size(8字节LE=32) + capacity 首字节(0x1f/0x2f/0x3f)，指针在它前面 8 字节
_STR32_PAT = re.compile(rb"\x20\x00\x00\x00\x00\x00\x00\x00[\x1f\x2f\x3f]\x00")
# 通用 std::string 扫描：size ∈ {32,64,96,98}（passphrase/hex 串/pragma 串）
_STRX_PAT = re.compile(rb"[\x20\x40\x60\x62\x64]\x00\x00\x00\x00\x00\x00\x00\x00[\x1f-\xff]\x00")
MAX_PASS_CANDS = 400

# WCDB Config.Cipher 值被微信用一段固定代码字节做 XOR 混淆（4.1+ 常见）
CONFIG_XOR_MASK = bytes.fromhex(
    "d2c7442458020000004889442450488b450048844c2448488944254048584c24"
)
_HEX_CHARS = set(b"0123456789abcdefABCDEF")

# 图片解密密钥：16~32 字符字母数字 ASCII 串（边界对齐），配合已知明文验证
_RE_ALNUM = re.compile(rb"(?<![a-zA-Z0-9])[a-zA-Z0-9]{16,32}(?![a-zA-Z0-9])")
MAX_ALNUM = 300000


def find_wechat_pids() -> list[int]:
    """返回所有 Weixin.exe / WeChatAppEx.exe 进程 PID（主进程在前）。仅 Windows。

    用 ctypes 调 CreateToolhelp32Snapshot 枚举进程 —— 不产生任何子进程/控制台窗口
    （打包成无窗口 exe 后也不会闪黑框）。
    """
    if not _IS_WIN:
        return []
    pids: list[int] = []
    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_uint32),
            ("cntThreads", ctypes.c_uint32),
            ("th32ParentProcessID", ctypes.c_uint32),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_uint32),
            ("szExeFile", ctypes.c_wchar * MAX_PATH),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if h in (0, -1):
        return pids
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(h, ctypes.byref(entry)):
            return pids
        while True:
            name = entry.szExeFile.lower()
            if name in ("weixin.exe", "wechatappex.exe"):
                pids.append(entry.th32ProcessID)
            if not kernel32.Process32NextW(h, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(h))
    return pids


def find_data_dirs() -> list[str]:
    """定位所有账号的 db_storage 目录（只探测，不写盘）。仅 Windows。"""
    if not _IS_WIN:
        return []
    candidates: list[str] = []

    def _add(path: str) -> None:
        path = os.path.normpath(path)
        if os.path.isdir(path) and path not in candidates:
            candidates.append(path)

    # 1) Documents 默认位置 / 自定义“个人文件夹”
    for env in ("USERPROFILE", "ONEDRIVE", "OneDriveConsumer"):
        base = os.environ.get(env)
        if base:
            _add(os.path.join(base, "Documents", "xwechat_files"))
    # 2) 注册表里常见的数据目录键
    try:
        import winreg

        for key_path in (r"Software\Tencent\Weixin", r"Software\Tencent\WeChat"):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                    for i in range(winreg.QueryInfoKey(k)[1]):
                        name, value, _ = winreg.EnumValue(k, i)
                        if isinstance(value, str) and ("Files" in value or "xwechat" in value.lower()):
                            _add(os.path.join(value, "xwechat_files") if "xwechat_files" not in value else value)
            except OSError:
                pass
    except Exception:
        pass
    # 3) 常见自定义盘符根目录浅层探测
    for drive in ("C:", "D:", "E:", "F:"):
        for sub in (
            os.path.join(drive, os.sep, "xwechat_files"),
            os.path.join(drive, os.sep, "WeChat Files"),
            os.path.join(drive, os.sep, "personal", "Documents", "xwechat_files"),
        ):
            _add(sub)

    valid = []
    for c in candidates:
        if os.path.basename(c) == "xwechat_files" and any(
            os.path.isdir(os.path.join(c, d, "db_storage")) for d in os.listdir(c)
        ):
            valid.append(c)
    return valid


def list_accounts(data_dir: str) -> list[str]:
    """xwechat_files 下的账号目录（含 db_storage 的）。"""
    accounts = []
    for name in os.listdir(data_dir):
        if os.path.isdir(os.path.join(data_dir, name, "db_storage")):
            accounts.append(name)
    return sorted(accounts)


def db_salt(path: str) -> str | None:
    """加密库第一页前 16 字节即 salt。"""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
        if len(head) < 4096:
            return None
        return head[:16].hex()
    except OSError:
        return None


@dataclass
class ScanResult:
    # salt_hex -> {key_hex, ...}（salt 精确配对）
    keys_by_salt: dict[str, set[str]] = field(default_factory=dict)
    candidates: set[str] = field(default_factory=set)   # 所有 x'...' 候选原文
    bare_keys: set[str] = field(default_factory=set)    # 仅 64hex key（需 HMAC 验证配对）
    pass_candidates: dict[str, int] = field(default_factory=dict)  # 4.1+ passphrase hex -> 出现次数
    alnum: set[str] = field(default_factory=set)        # 16~32 字母数字串（图片密钥候选）
    scanned_pids: list[int] = field(default_factory=list)
    failed_pids: list[int] = field(default_factory=list)


def _iter_readable_regions(h: int):
    addr = 0
    mbi = MEMORY_BASIC_INFORMATION()
    while addr < 0x7FFFFFFFFFF:
        got = kernel32.VirtualQueryEx(
            ctypes.c_void_p(h), ctypes.c_uint64(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
        )
        if got == 0:
            break
        size = mbi.RegionSize
        nxt = mbi.BaseAddress + size
        if nxt <= addr:
            break
        if mbi.State == MEM_COMMIT and mbi.Protect not in (PAGE_NOACCESS, PAGE_GUARD) and 0 < size <= MAX_REGION:
            # 只扫可读页
            if mbi.Protect in (0x02, 0x04, 0x08, 0x20, 0x40) or (mbi.Protect & 0xEE):
                yield mbi.BaseAddress, size
        addr = nxt


def _is_probable_passphrase(b: bytes) -> bool:
    """启发式过滤 32 字节 passphrase：熵要够高，不能是 ASCII 文本/指针。"""
    if len(b) != 32:
        return False
    if len(set(b)) < 15:
        return False
    if all(x == 0 for x in b) or all(x == 0xFF for x in b):
        return False
    printable = sum(1 for x in b if 32 <= x <= 126)
    return printable <= 24


def _add_hex_literal(result: ScanResult, s: str) -> None:
    """把一段 hex 字面量按长度归入候选（key+salt / 纯 key）。"""
    s = s.strip().lower()
    if len(s) >= 96:
        key, salt = s[:64], s[-32:]
        result.candidates.add("x'" + s + "'")
        result.keys_by_salt.setdefault(salt, set()).add(key)
        # key 部分同时进入 bare_keys：4.1 中它是 passphrase，可对其它 salt 不同的库派生验证
        if len(result.bare_keys) < MAX_BARE_KEYS:
            result.bare_keys.add(key)
    elif len(s) == 64 and len(result.bare_keys) < MAX_BARE_KEYS:
        result.candidates.add(s)
        result.bare_keys.add(s)


def _scan_xor_masked(result: ScanResult, data: bytes) -> int:
    """在内存块中搜索被 CONFIG_XOR_MASK 循环异或混淆的 x'<hex>' 字面量。"""
    found = 0
    mask = CONFIG_XOR_MASK
    mlen = len(mask)
    view = bytes(data)
    for r in range(mlen):
        needle = bytes((mask[r] ^ 0x78, mask[(r + 1) % mlen] ^ 0x27))  # 编码后的 "x'"
        pos = view.find(needle)
        while pos >= 0:
            end = pos + 2
            ok = True
            while end < len(view) and end - pos < 200:
                c = view[end] ^ mask[(r + end - pos) % mlen]
                if c == 0x27:  # 结束引号
                    break
                if c not in _HEX_CHARS:
                    ok = False
                    break
                end += 1
            if ok and end - pos >= 66:
                s = bytes(view[pos + 2 + i] ^ mask[(r + 2 + i) % mlen]
                          for i in range(end - pos - 2)).decode("ascii", errors="ignore")
                if len(s) >= 64:
                    _add_hex_literal(result, s)
                    found += 1
            pos = view.find(needle, pos + 1)
    return found


def scan_pid(pid: int, result: ScanResult, log=lambda m: None) -> int:
    """扫描单个进程，返回本次新发现的候选数。"""
    h = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        result.failed_pids.append(pid)
        log(f"  进程 {pid} 无法打开（权限不足或已退出）")
        return 0
    found = 0
    str_ptrs: set[int] = set()
    strx_ptrs: list[tuple[int, int]] = []
    try:
        for base, size in _iter_readable_regions(h):
            offset = 0
            while offset < size:
                read_len = min(CHUNK, size - offset)
                buf = ctypes.create_string_buffer(read_len + OVERLAP)
                nread = ctypes.c_size_t(0)
                ok = kernel32.ReadProcessMemory(
                    ctypes.c_void_p(h),
                    ctypes.c_uint64(base + offset),
                    buf,
                    ctypes.c_size_t(read_len + OVERLAP),
                    ctypes.byref(nread),
                )
                if ok and nread.value > 0:
                    data = buf.raw[: nread.value]
                    for m in _HEX_PAT.finditer(data):
                        wrapped, bare = m.group(1), m.group(2)
                        if bare:
                            s = bare.decode("ascii")
                            if s in result.candidates:
                                continue
                            result.candidates.add(s)
                            key, salt = s[:64].lower(), s[64:].lower()
                            result.keys_by_salt.setdefault(salt, set()).add(key)
                            found += 1
                        elif wrapped:
                            s = wrapped.decode("ascii")
                            if s in result.candidates:
                                continue
                            result.candidates.add(s)
                            found += 1
                            if len(s) == 64:
                                if len(result.bare_keys) < MAX_BARE_KEYS:
                                    result.bare_keys.add(s.lower())
                            else:
                                key, salt = s[:64].lower(), s[-32:].lower()
                                result.keys_by_salt.setdefault(salt, set()).add(key)
                    for m in _STR32_PAT.finditer(data):
                        if m.start() < 8:
                            continue
                        ptr = int.from_bytes(data[m.start() - 8: m.start()], "little")
                        if 0x10000 <= ptr < 0x7FFFFFFFFFF and len(str_ptrs) < MAX_PASS_CANDS * 4:
                            str_ptrs.add(ptr)
                    for m in _STRX_PAT.finditer(data):
                        if m.start() < 8:
                            continue
                        ptr = int.from_bytes(data[m.start() - 8: m.start()], "little")
                        sz = data[m.start()]
                        if 0x10000 <= ptr < 0x7FFFFFFFFFF and len(strx_ptrs) < MAX_PASS_CANDS * 4:
                            strx_ptrs.append((ptr, sz))
                    for m in _RE_ALNUM.finditer(data):
                        s = m.group()
                        if s not in result.alnum and len(result.alnum) < MAX_ALNUM:
                            result.alnum.add(s)
                    found += _scan_xor_masked(result, data)
                if read_len < CHUNK:
                    break
                offset += read_len - OVERLAP

        # 读取 std::string 指向的候选内容
        out = ctypes.create_string_buffer(256)
        nread = ctypes.c_size_t(0)

        def _read(ptr: int, n: int) -> bytes | None:
            if kernel32.ReadProcessMemory(ctypes.c_void_p(h), ctypes.c_uint64(ptr),
                                          out, ctypes.c_size_t(n), ctypes.byref(nread)) and nread.value == n:
                return out.raw[:n]
            return None

        for ptr in str_ptrs:
            b = _read(ptr, 32)
            if b and _is_probable_passphrase(b):
                h_hex = b.hex()
                result.pass_candidates[h_hex] = result.pass_candidates.get(h_hex, 0) + 1
                found += 1
        for ptr, sz in strx_ptrs:
            n = min(256, max(32, sz + 3))
            v = _read(ptr, n)
            if not v:
                continue
            if v[:2] in (b"x'", b"X'"):
                for lit in re.findall(rb"'([0-9a-fA-F]{64,192})'", v):
                    _add_hex_literal(result, lit.decode("ascii"))
                    found += 1
            elif sz in (64, 96, 98) and all(c in _HEX_CHARS for c in v[:sz]):
                _add_hex_literal(result, v[:sz].decode("ascii"))
                found += 1
        result.scanned_pids.append(pid)
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(h))
    return found


def collect_salts(storage_dir: str, subnames: tuple[str, ...]) -> dict[str, list[str]]:
    """收集指定库文件的 salt。返回 salt_hex -> [db文件绝对路径,...]"""
    salts: dict[str, list[str]] = {}
    for root, _dirs, files in os.walk(storage_dir):
        for f in files:
            if not f.endswith(".db"):
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, storage_dir).replace("\\", "/")
            if not any(sub in rel for sub in subnames):
                continue
            # 索引/资源类库对聊天导出无用，且句柄可能未打开、密钥不在内存
            # hardlink/emoticon 保留：消息↔媒体映射与表情包元数据
            if any(x in rel for x in ("_fts", "resource", "media_", "weclaw")):
                continue
            s = db_salt(path)
            if s:
                salts.setdefault(s, []).append(path)
    return salts


def scan_memory(log=lambda m: None, progress=lambda cur, total: None) -> ScanResult:
    """扫描微信进程内存，收集密钥/passphrase 候选。

    优化：密钥只存在于 Weixin.exe 主进程（无 --type 子进程参数），
    先只扫主进程，找到候选即返回；主进程没找到才扫全部子进程兜底。
    """
    result = ScanResult()
    pids = find_wechat_pids()
    if not pids:
        raise RuntimeError("未找到微信进程（Weixin.exe），请先登录微信再试")
    log(f"发现 {len(pids)} 个微信相关进程: {pids}")

    # 区分主进程与子进程：一次快照拿 {pid: parent_pid}（无子进程，不闪窗）
    # 主进程 = Weixin.exe 中 parent 不是 Weixin 的（子进程的 parent 是主进程）
    parents = _pid_parents()
    main_pids = set()
    for pid in pids:
        par = parents.get(pid)
        if par is None or par not in pids:
            main_pids.add(pid)

    mains = [p for p in pids if p in main_pids]
    total = len(pids)
    for i, pid in enumerate(mains):
        progress(i, total)
        n = scan_pid(pid, result, log)
        if n:
            log(f"  主进程 {pid} 新增 {n} 个候选")
    if result.candidates or result.keys_by_salt or result.pass_candidates:
        log(f"主进程已找到候选（{len(result.candidates)}），跳过子进程扫描")
        progress(total, total)
        return result
    # 兜底：扫全部
    log("主进程未找到候选，扫描全部进程…")
    for i, pid in enumerate(pids):
        if pid in mains:
            continue
        progress(i, total)
        n = scan_pid(pid, result, log)
        if n:
            log(f"  进程 {pid} 新增 {n} 个候选")
    progress(total, total)
    return result


def _pid_parents() -> dict[int, int]:
    """返回 {pid: parent_pid}（进程快照，一次调用，无子进程）。"""
    parents: dict[int, int] = {}
    if not _IS_WIN:
        return parents
    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260

    class PE32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ProcessID", ctypes.c_uint32),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_uint32),
            ("cntThreads", ctypes.c_uint32),
            ("th32ParentProcessID", ctypes.c_uint32),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_uint32),
            ("szExeFile", ctypes.c_wchar * MAX_PATH),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if h in (0, -1):
        return parents
    try:
        e = PE32W()
        e.dwSize = ctypes.sizeof(PE32W)
        if not kernel32.Process32FirstW(h, ctypes.byref(e)):
            return parents
        while True:
            parents[e.th32ProcessID] = e.th32ParentProcessID
            if not kernel32.Process32NextW(h, ctypes.byref(e)):
                break
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(h))
    return parents


def match_keys(storage_dir: str, result: ScanResult,
               log=lambda m: None,
               want_patterns: tuple[str, ...] = ("contact", "message", "session", "hardlink", "emoticon")) -> dict[str, str]:
    """把扫描结果与指定账号 db_storage 下的库做匹配，返回 {db路径: 'key+salt' hex}。"""
    salts = collect_salts(storage_dir, want_patterns)
    if not salts:
        raise RuntimeError(f"目录 {storage_dir} 下没有找到任何加密数据库文件")
    log(f"共 {len(salts)} 个目标数据库待匹配密钥")

    matched: dict[str, str] = {}
    unmatched: list[str] = []
    for salt, dbs in salts.items():
        keys = result.keys_by_salt.get(salt)
        if keys:
            for db in dbs:
                matched[db] = next(iter(keys)) + salt
        else:
            unmatched.extend(dbs)

    # salt 没配上的库：用「仅 key」候选逐个 HMAC 验证（HMAC 校验即确认）
    if unmatched and result.bare_keys:
        from . import decrypt as _decrypt

        log(f"{len(unmatched)} 个库 salt 未直接命中，尝试 {len(result.bare_keys)} 个纯 key 候选…")
        still = []
        for db in unmatched:
            for k in result.bare_keys:
                if _decrypt.verify_key(db, k):
                    with open(db, "rb") as fh:
                        salt_hex = fh.read(16).hex()
                    matched[db] = k + salt_hex
                    log(f"    {os.path.basename(db)}: 纯 key 候选验证通过")
                    break
            else:
                still.append(db)
        unmatched = still

    # 4.1+：passphrase 需 PBKDF2-SHA512(256000) 派生后验证。
    # passphrase 在每个打开的库句柄里各有一份，按出现频次排序可大幅减少验证次数。
    if unmatched and result.pass_candidates:
        from . import decrypt as _decrypt

        cands = sorted(result.pass_candidates.items(), key=lambda kv: -kv[1])
        log(f"尝试 {len(cands)} 个 passphrase 候选（按出现频次排序，PBKDF2-256k 派生验证）…")
        rep = min(unmatched, key=os.path.getsize)
        found_pass = None
        for p, cnt in cands:
            if cnt < 2:
                break  # 真正的 passphrase 至少伴随多个打开的库出现
            if _decrypt.verify_key(rep, p):
                found_pass = p
                log(f"    passphrase 验证通过（出现 {cnt} 次）")
                break
        if found_pass:
            for db in unmatched:
                with open(db, "rb") as fh:
                    salt_hex = fh.read(16).hex()
                matched[db] = found_pass + salt_hex
            unmatched = []

    log(f"已匹配 {len(matched)}/{len(salts)} 个数据库的密钥")
    return matched


def scan_keys(storage_dir: str, log=lambda m: None, progress=lambda cur, total: None,
              want_patterns: tuple[str, ...] = ("contact", "message", "session")) -> tuple[dict[str, str], ScanResult]:
    """兼容入口：扫描 + 匹配一步完成。"""
    result = scan_memory(log=log, progress=progress)
    matched = match_keys(storage_dir, result, log=log, want_patterns=want_patterns)
    return matched, result
