# -*- coding: utf-8 -*-
"""实时聊天监视器：增量检测微信 -wal 新帧并合入本地副本（最小时间/空间）。"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time

from . import decrypt


class ChatWatcher:
    """监听一个账号的解密数据目录，有新消息时触发回调。

    复杂度：
      - 轮询开销 O(库数) 次 os.stat（几乎不读盘；未变化的 -wal 只读 32 字节头）
      - 合并开销 O(新增帧数)（只对新帧执行一次 AES-ECB 解密 + 一次定位写）
      - 空间 O(1) 额外（只保留每个 -wal 的 上一代salt + 上次字节偏移）
    """

    def __init__(self, account: str, decrypted_root: str, storage_dir: str,
                 keyfile: str, on_update, poll_interval: float = 1.5):
        self.account = account
        self.decrypted_root = decrypted_root
        self.storage_dir = storage_dir
        self.keyfile = keyfile
        self.on_update = on_update
        self.interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._keys: dict[str, str] = {}
        self._load_keys()

        # 每个库的增量状态：db_rel -> (上一代salt(bytes8), 已处理到的文件偏移)
        self._state: dict[str, tuple[bytes, int]] = {}

    # ------------------------------------------------------------ 基础

    def _load_keys(self) -> None:
        import json
        try:
            with open(self.keyfile, "r", encoding="utf-8") as f:
                self._keys = json.load(f)
        except Exception:
            self._keys = {}

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True, name="chat-watcher")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------ 主循环

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:
                pass
            self._stop.wait(self.interval)

    def _poll_once(self) -> None:
        if not os.path.isdir(self.storage_dir):
            return
        changed = set()
        for db_rel, wal, stat in self._iter_wal(self.storage_dir):
            key_full = self._keys.get(db_rel)
            if not key_full or len(key_full) < 64:
                continue
            changed |= self._process_wal(db_rel, wal, stat, key_full)
        if changed:
            try:
                self.on_update(changed)
            except Exception:
                pass

    # ------------------------------------------------------------ 目录扫描（一次 scandir）

    def _iter_wal(self, storage_dir: str, root: str | None = None):
        """单次递归 scandir，产出所有消息库：(db相对路径, wal或db路径, 复合指纹)。

        指纹 = (wal_mtime_ns, wal_size, db_mtime_ns, db_size) —— 主库与 wal 任一变化
        都会触发处理，避免 checkpoint 后 wal 指纹没变但主库有新消息的漏检。
        """
        root = root or storage_dir
        try:
            entries = list(os.scandir(storage_dir))
        except OSError:
            return
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                yield from self._iter_wal(e.path, root)
            elif e.is_file(follow_symlinks=False) and e.name.endswith(".db"):
                wal = e.path + "-wal"
                path = wal
                try:
                    wst = os.stat(wal)
                    w_sig = (wst.st_mtime_ns, wst.st_size)
                except OSError:
                    path = e.path
                    w_sig = (0, 0)
                try:
                    dst = os.stat(e.path)
                    d_sig = (dst.st_mtime_ns, dst.st_size)
                except OSError:
                    d_sig = (0, 0)
                rel = os.path.relpath(e.path, root).replace("\\", "/")
                yield rel, path, (w_sig, d_sig)

    # ------------------------------------------------------------ WAL 增量处理

    def _process_wal(self, db_rel: str, path: str, stat, key_full: str) -> set:
        """增量：指纹不变→跳过；变了→重解主库（含 wal）或增量合并 wal。

        返回受影响的表名集合。sig = ((wal_mtime,wal_size),(db_mtime,db_size))
        """
        sig = stat
        last = self._state.get(db_rel)
        if last is not None and last[0] == sig:
            return set()  # 完全未变，零成本跳过

        db_path = os.path.join(self.storage_dir, db_rel.replace("/", os.sep))
        out_path = os.path.join(self.decrypted_root, self.account, db_rel.replace("/", os.sep))
        wal = path
        wal_exists = wal.endswith("-wal")

        # 主库指纹变了（checkpoint 后新消息进主库）→ 直接重解主库（decrypt 内含 wal 合并）
        if wal_exists:
            db_sig = sig[1]
            if db_sig and db_sig != (0, 0) and (not last or last[1] != db_sig):
                try:
                    from . import decrypt as _d
                    r = _d.decrypt_database(db_path, out_path, key_full[:64], log=lambda m: None)
                    self._state[db_rel] = (sig, db_sig)
                    if r["ok"]:
                        return self._chat_tables(db_rel)
                except Exception:
                    pass
                self._state[db_rel] = (sig, db_sig)
                return set()
        else:
            # 无 wal：主库变了直接重解
            try:
                from . import decrypt as _d
                r = _d.decrypt_database(db_path, out_path, key_full[:64], log=lambda m: None)
                self._state[db_rel] = (sig, (0, 0))
                if r["ok"]:
                    return self._chat_tables(db_rel)
            except Exception:
                pass
            self._state[db_rel] = (sig, (0, 0))
            return set()

        # wal 增量路径：读头判断当前代，增量合并新帧
        try:
            with open(wal, "rb") as f:
                head = f.read(56)
        except OSError:
            return set()
        if len(head) < 56:
            self._state[db_rel] = (sig, sig[1] if wal_exists else (0, 0))
            return set()
        if int.from_bytes(head[0:4], "big") not in (0x377F0682, 0x377F0683):
            self._state[db_rel] = (sig, sig[1] if wal_exists else (0, 0))
            return set()
        if int.from_bytes(head[8:12], "big") != 4096:
            self._state[db_rel] = (sig, sig[1] if wal_exists else (0, 0))
            return set()
        gen = head[40:48]
        w_size = sig[0][1] if wal_exists else 0
        total = w_size

        # 计算增量起点：微信 4.x 循环复用 wal（size 不变、覆盖写），
        # 不能依赖 last_off——wal mtime 变了就从头读当前代重新合并（幂等，值一致重写无害）
        gen = head[40:48]
        start = 32
        total = w_size
        if start >= total:
            self._state[db_rel] = (sig, sig[1] if wal_exists else (0, 0))
            return set()

        # 读当前代全部帧（32..total）——微信 wal 几 MB，一次读完快
        try:
            with open(wal, "rb") as f:
                f.seek(start)
                seg = f.read(total - start)
        except OSError:
            return set()
        out_path = os.path.join(self.decrypted_root, self.account, db_rel.replace("/", os.sep))
        n = _merge_new_frames(seg, gen, start, out_path, key_full)
        self._state[db_rel] = (sig, sig[1] if wal_exists else (0, 0))
        if n:
            return self._chat_tables(db_rel)
        return set()

    # ------------------------------------------------------------ 辅助

    def _chat_tables(self, db_rel: str) -> set:
        """该库中哪些 chat 表（Msg_<32hex>）——返回 talker 表名集合，用于精确刷新。"""
        out_path = os.path.join(self.decrypted_root, self.account, db_rel.replace("/", os.sep))
        if not os.path.isfile(out_path):
            return set()
        try:
            conn = sqlite3.connect(f"file:{out_path}?mode=ro&immutable=1", uri=True)
            names = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")
                if re.fullmatch(r"Msg_[0-9a-f]{32}", r[0])]
            conn.close()
            return set(names)
        except Exception:
            return set()

    def log(self, m: str) -> None:
        pass


def _merge_new_frames(seg: bytes, gen: bytes, start: int, out_path: str, key_full: str) -> int:
    """把 seg（从 wal 的绝对偏移 start 处读出的段）里属于当前代 gen、且已提交的帧增量合并。

    返回实际写入的帧数。帧在 wal 中的绝对偏移 = 32 + k*4120；
    seg 内偏移 = 绝对偏移 - start。这里只要求 start 为帧边界（或 32）。
    """
    frame_sz = 24 + 4096
    # start 必须是帧边界：wal 中帧边界 = 32 + k*frame_sz
    if start < 32 or (start - 32) % frame_sz:
        # 非边界：从 wal 最开头的帧开始处理（保守），等价于 start=32
        rel_off = 32 - start if start <= 32 else 0  # seg 内：若 start>32 且非边界，不完整
        if start != 32:
            return 0  # 只接受 start=32 或帧边界
        rel_off = 0
    else:
        rel_off = 0  # start 已是边界，seg[0] 即第一个帧头

    if rel_off + frame_sz > len(seg):
        return 0

    # AES 密钥：从已解密主库第一页取 salt，派生（与解密主库一致的 raw-key 参数）
    try:
        with open(out_path, "rb") as f:
            db_head = f.read(4096)
        aes_key = decrypt._derive_aes_key(
            bytes.fromhex(key_full[:64]), db_head[:16], decrypt.V4)
    except Exception:
        return 0

    # 当前代 salt 校验：seg 起始帧的 salt 必须等于 gen
    if seg[rel_off + 8: rel_off + 16] != gen:
        return 0  # 起点已是新代（上一代被 checkpoint），等下次再合并

    # 逐帧解析，只处理与 gen 相同的连续帧，到最后一个 commit 为止
    latest: dict[int, bytes] = {}
    db_size_pages = 0
    commit_at = -1
    it = rel_off
    while it + frame_sz <= len(seg):
        if seg[it + 8: it + 16] != gen:
            break
        pgno = int.from_bytes(seg[it: it + 4], "big")
        commit = int.from_bytes(seg[it + 4: it + 8], "big")
        if pgno < 1:
            break
        pg = seg[it + 24: it + 24 + 4096]
        try:
            dec = decrypt._decrypt_page(pg, pgno, aes_key, decrypt.V4)
        except Exception:
            break
        latest[pgno] = dec
        if commit:
            db_size_pages = commit
            commit_at = len(latest)
        it += frame_sz

    if not latest or commit_at <= 0:
        return 0
    committed = {k: v for k, v in list(latest.items())[:commit_at]}

    # 原子写：读整库 → 应用帧 → 写临时文件 → os.replace 替换。
    # 避免与 UI 线程的读取并发导致 "malformed"（UI 永远读到完整快照）。
    try:
        with open(out_path, "rb") as fi:
            cur_data = bytearray(fi.read())
    except OSError:
        return 0
    cur = len(cur_data) // 4096
    # 内容变化检测：只应用与当前不同的页（微信可能覆盖写，页号相同但内容新）
    changed = 0
    for pgno, page in committed.items():
        off = (pgno - 1) * 4096
        if off + 4096 <= len(cur_data):
            if cur_data[off: off + 4096] == page:
                continue
        changed += 1
        if off + 4096 > len(cur_data):
            cur_data.extend(b"\x00" * (off + 4096 - len(cur_data)))
        cur_data[off: off + 4096] = page
    if changed == 0:
        return 0  # 帧内容与副本一致，无需写（避免每次 mtime 变化都重写）

    target = max(len(cur_data) // 4096, db_size_pages or 0)
    if db_size_pages and len(cur_data) // 4096 > db_size_pages:
        del cur_data[db_size_pages * 4096:]
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as fo:
        fo.write(cur_data)
        fo.flush()
        os.fsync(fo.fileno())
    os.replace(tmp, out_path)
    return changed