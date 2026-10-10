# -*- coding: utf-8 -*-
"""账号信息：列出本机所有微信账号，判断哪个正在登录，并给出可读昵称。

背景（已实测）：
- 微信 4.x 的账号目录形如 wxid_xxxxxxxxxxxx_ab12，一个目录一个账号；
- 密钥只存在于「当前登录」的那个微信进程里，且不一定能扫到；所以能否解密
  以「已解密过 / 已保存密钥文件」为准，而不是以内存扫描为准；
- 正在使用的账号会持续写 db_storage，所以用写入时间判断谁在线最可靠。
"""
from __future__ import annotations

import json
import os
import re
import time

from . import memscan

# 账号目录名形如 wxid_xxxxxxxxxxxxxxxx_ab12
_ACCOUNT_RE = re.compile(r"(?:wxid_[a-zA-Z0-9]{8,24}|gh_[a-z0-9]{8,20})_[a-zA-Z0-9]{4,8}")

# 最近这么长时间内写过 db_storage 就认为「客户端正在用这个账号」
ONLINE_WINDOW = 2 * 3600.0


def _db_mtime(data_dir: str, account: str) -> float:
    """账号数据最近写入时间（正在使用的账号会持续写）。"""
    newest = 0.0
    db = os.path.join(data_dir, account, "db_storage")
    for root, _dirs, files in os.walk(db):
        for fn in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, fn)))
            except OSError:
                pass
    return newest


def _self_nickname(decrypted_root: str, account: str) -> str:
    """从已解密库读自己的昵称（contact 表里本人那一条）。"""
    if not decrypted_root:
        return ""
    try:
        from .models import Store
        st = Store(decrypted_root, account)
        me = st.self_wxid()
        for c in st.contacts():
            if c.get("username") == me or c.get("is_self"):
                name = str(c.get("remark") or c.get("nick_name")
                           or c.get("alias") or "").strip()
                if name:
                    return name
        return (st.display_name(me) or "").strip()
    except Exception:
        return ""


def _contact_dbs(storage: str) -> list[str]:
    hits = []
    for root, _dirs, files in os.walk(storage):
        for fn in files:
            low = fn.lower()
            if low.endswith((".db", ".sqlite")) and "contact" in low and "_fts" not in low:
                hits.append(os.path.join(root, fn))
    return sorted(hits)


# ---------------------------------------------------------------- 昵称缓存

def _cache_path(data_root: str) -> str:
    return os.path.join(data_root, "account_nicknames.json")


def load_nickname_cache(data_root: str) -> dict:
    try:
        with open(_cache_path(data_root), "r", encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def save_nickname(data_root: str, account: str, nickname: str) -> None:
    """缓存昵称，让未解密的账号也能显示名字。"""
    if not data_root or not account or not nickname:
        return
    try:
        os.makedirs(data_root, exist_ok=True)
        cache = load_nickname_cache(data_root)
        if cache.get(account) == nickname:
            return
        cache[account] = nickname
        with open(_cache_path(data_root), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


# ------------------------------------------------------------ 内存/昵称补充

def _read_memory_strings(pid: int, pattern: re.Pattern) -> set[str]:
    """读进程内存，按 ASCII 与 UTF-16LE 两种编码找 pattern。"""
    import ctypes
    k32 = memscan.kernel32
    h = k32.OpenProcess(0x1000 | 0x0010, False, pid)  # QUERY_LIMITED | VM_READ
    if not h:
        return set()
    found: set[str] = set()
    try:
        for base, size in memscan._iter_readable_regions(h):
            n = min(size, 1 << 26)
            buf = ctypes.create_string_buffer(n)
            rd = ctypes.c_size_t(0)
            if not k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, n,
                                         ctypes.byref(rd)):
                continue
            data = buf.raw[:rd.value]
            found.update(pattern.findall(data.decode("latin-1")))
            if b"\x00" in data:
                found.update(pattern.findall(data.decode("utf-16-le", "ignore")))
    except Exception:
        pass
    finally:
        k32.CloseHandle(h)
    return found


def detect_memory_accounts() -> set[str]:
    """扫微信进程内存，返回出现过的账号 wxid（不含目录实例后缀）。

    注意：多开/切换过的账号可能都残留在内存里，所以这只能说明「这个账号本机
    登录过」，不能单独用来判断谁在线。
    """
    pids = memscan.find_wechat_pids()
    if not pids:
        return set()
    pat = re.compile(r"(?:wxid_[a-zA-Z0-9]{10,24}|gh_[a-z0-9]{10,20})")
    parents = memscan._pid_parents()
    mains = [p for p in pids if parents.get(p) not in pids] or pids
    out: set[str] = set()
    for pid in mains:
        out |= _read_memory_strings(pid, pat)
    return out


def _nickname_from_encrypted(data_dir: str, account: str, key_hex: str) -> str:
    """用已知密钥临时解出 contact 库读昵称（账号还没正式解密时用）。"""
    import shutil
    import sqlite3
    import tempfile
    from . import decrypt as _decrypt
    dbs = _contact_dbs(os.path.join(data_dir, account, "db_storage"))
    if not dbs:
        return ""
    tmpdir = tempfile.mkdtemp(prefix="wcnick_")
    try:
        for i, db in enumerate(dbs):
            out = os.path.join(tmpdir, f"c{i}.db")
            try:
                r = _decrypt.decrypt_database(db, out, key_hex[:64])
            except Exception:
                continue
            if not r.get("ok"):
                continue
            rows = []
            try:
                conn = sqlite3.connect(out)
                try:
                    rows = conn.execute(
                        "SELECT username, remark, nick_name, alias, flag FROM contact"
                    ).fetchall()
                finally:
                    conn.close()
            except Exception:
                continue
            # 优先：username 与 alias 相同的本人条目
            for un, remark, nick, alias, flag in rows:
                un = un or ""
                if not un or un.endswith("@chatroom"):
                    continue
                name = str(remark or nick or "").strip()
                if name and alias and un == alias:
                    return name
            # 兜底：wxid_ 开头且 flag 置位的本人条目
            for un, remark, nick, alias, flag in rows:
                un = un or ""
                name = str(remark or nick or "").strip()
                if name and un.startswith("wxid_") and flag in (1, 8, 9):
                    return name
        return ""
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- 对外接口

def _saved_key_works(keys_dir: str, account: str, data_dir: str) -> bool:
    """检查账号已保存的密钥文件是否还能通过 HMAC 校验。"""
    kf = os.path.join(keys_dir, f"{account}.json")
    if not os.path.isfile(kf):
        return False
    try:
        with open(kf, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        return False
    if not isinstance(saved, dict) or not saved:
        return False
    from . import decrypt as _decrypt
    storage = os.path.join(data_dir, account, "db_storage")
    checked = 0
    for rel, key in saved.items():
        db = os.path.join(storage, str(rel).replace("/", os.sep))
        if not os.path.isfile(db) or not key:
            continue
        checked += 1
        try:
            if _decrypt.verify_key(db, str(key)[:64]):
                return True
        except Exception:
            continue
    return checked == 0


def list_accounts_info(decrypted_root: str = "", keys_dir: str = "",
                       online_map: dict | None = None,
                       data_root: str = "",
                       verify_saved_keys: bool = False) -> list[dict]:
    """列出本机所有微信账号（在线 / 昵称 / 解密状态 / 能否解密）。

    verify_saved_keys=True 会逐个用 HMAC 校验已保存密钥（慢，约几秒）。
    """
    cache = load_nickname_cache(data_root) if data_root else {}
    now = time.time()
    seen: set[str] = set()
    out: list[dict] = []
    for data_dir in memscan.find_data_dirs():
        for account in memscan.list_accounts(data_dir):
            if account in seen:
                continue
            seen.add(account)
            mt = _db_mtime(data_dir, account)
            age = (now - mt) if mt else float("inf")
            dec = bool(decrypted_root
                       and os.path.isdir(os.path.join(decrypted_root, account))
                       and any(os.scandir(os.path.join(decrypted_root, account))))
            kf = os.path.join(keys_dir, f"{account}.json") if keys_dir else ""
            has_keys = bool(kf and os.path.isfile(kf))
            nick = _self_nickname(decrypted_root, account) if dec else ""
            nick = nick or cache.get(account, "")
            if nick and data_root and not cache.get(account):
                save_nickname(data_root, account, nick)
            can_dec = dec
            if not can_dec and has_keys and verify_saved_keys:
                can_dec = _saved_key_works(keys_dir, account, data_dir)
            elif not can_dec and has_keys:
                can_dec = True
            info = {
                "account": account,
                "nickname": nick,
                "data_dir": data_dir,
                "mtime": mt,
                "age": age,
                "decrypted": dec,
                "has_keys": has_keys,
                "can_decrypt": can_dec,
                "online": age <= ONLINE_WINDOW,
                "online_hint": "",
                "in_memory": False,
            }
            if online_map:
                info["in_memory"] = account.split("_")[0] in online_map
            if info["online"]:
                info["online_hint"] = "客户端正在使用"
            out.append(info)
    out.sort(key=lambda x: (not x["online"], -x["mtime"]))
    return out


def probe_accounts(decrypted_root: str, keys_dir: str, data_root: str = "",
                   scan_memory: bool = True) -> list[dict]:
    """账号列表 + 密钥可用性 + 内存昵称补充（供账号选择弹窗使用）。"""
    online_map = None
    if scan_memory:
        try:
            online_map = {a: {} for a in detect_memory_accounts()}
        except Exception:
            online_map = None
    info = list_accounts_info(decrypted_root, keys_dir, online_map=online_map,
                              data_root=data_root)
    # 未解密但有密钥的账号：临时解出 contact 库把昵称补上
    from . import decrypt as _decrypt
    for a in info:
        if a["nickname"] or a["decrypted"] or not a["has_keys"]:
            continue
        account, data_dir = a["account"], a["data_dir"]
        try:
            with open(os.path.join(keys_dir, f"{account}.json"), "r",
                      encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            continue
        for db in _contact_dbs(os.path.join(data_dir, account, "db_storage")):
            for rel, key in saved.items():
                if os.path.basename(str(rel)) != os.path.basename(db) or not key:
                    continue
                try:
                    if not _decrypt.verify_key(db, str(key)[:64]):
                        continue
                except Exception:
                    continue
                nick = _nickname_from_encrypted(data_dir, account, str(key))
                if nick:
                    a["nickname"] = nick
                    save_nickname(data_root, account, nick)
                break
            if a["nickname"]:
                break
    return info