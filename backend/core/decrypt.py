# -*- coding: utf-8 -*-
"""纯 Python 实现的微信 4.x SQLCipher 数据库解密，不依赖 pysqlcipher3。

微信 4.0 (WCDB/SQLCipher 4) 页面参数：
    page_size = 4096
    AES-256-CBC，密钥 = 内存中提取的 32 字节 enc_key（raw key，无 KDF）
    每页布局: [密文 ...][IV 16B][HMAC-SHA512 64B]，reserve = 80
    第 1 页前 16 字节为 salt（明文），解密输出时补回 SQLite 头
    mac_key = PBKDF2-HMAC-SHA512(enc_key, salt^0x3a, iter=2, dklen=32)
    页 HMAC = HMAC-SHA512(mac_key, 密文+IV + little-endian 页号)

旧参数变体（PBKDF2-SHA1 派生密钥 + HMAC-SHA1 + reserve=36）作为兜底，
以第 1 页 HMAC 校验结果自动选择。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import struct

from Crypto.Cipher import AES

SQLITE_HDR = b"SQLite format 3\x00"


class _Variant:
    __slots__ = ("name", "hmac_name", "hmac_sz", "iv_sz", "mac_iter", "mac_hash_name", "kdf")

    def __init__(self, name, hmac_name, hmac_sz, iv_sz, mac_iter, mac_hash_name, kdf):
        self.name = name
        self.hmac_name = hmac_name      # hmac.new 的 digestmod
        self.hmac_sz = hmac_sz
        self.iv_sz = iv_sz
        self.mac_iter = mac_iter        # mac key 的 PBKDF2 迭代数
        self.mac_hash_name = mac_hash_name
        self.kdf = kdf                  # "raw" | "pbkdf2_sha1_64000" | "pbkdf2_sha512_256000"


V4 = _Variant("sqlcipher4-hmacsha512", "sha512", 64, 16, 2, "sha512", "raw")
V41 = _Variant("wcdb41-pbkdf2sha512", "sha512", 64, 16, 2, "sha512", "pbkdf2_sha512_256000")
V4_SHA1 = _Variant("wcdb-hmacsha1", "sha1", 20, 16, 2, "sha1", "pbkdf2_sha1_64000")

VARIANTS = (V4, V41, V4_SHA1)


def _mac_key(enc_key: bytes, salt: bytes, var: _Variant) -> bytes:
    mac_salt = bytes(b ^ 0x3A for b in salt)
    return hashlib.pbkdf2_hmac(var.mac_hash_name, enc_key, mac_salt, var.mac_iter, dklen=32)


def _page1_mac_ok(enc_key: bytes, page1: bytes, var: _Variant, salt: bytes) -> bool:
    """校验第 1 页 HMAC，判断 enc_key/参数是否正确。"""
    reserve = var.iv_sz + var.hmac_sz
    if len(page1) < 4096:
        return False
    try:
        mac_key = _mac_key(enc_key, salt, var)
        data = page1[16 : 4096 - reserve + var.iv_sz]
        stored = page1[4096 - var.hmac_sz :]
        hm = hmac.new(mac_key, data, var.hmac_name)
        hm.update(struct.pack("<I", 1))
        return hmac.compare_digest(hm.digest(), stored)
    except Exception:
        return False


def verify_key(db_path: str, enc_key_hex: str) -> bool:
    """校验 64 位 hex enc_key 是否能解密该库（第 1 页 HMAC）。"""
    try:
        with open(db_path, "rb") as fh:
            page1 = fh.read(4096)
    except OSError:
        return False
    if len(page1) < 4096 or page1[:16] == SQLITE_HDR:
        return False  # 未加密或文件异常
    salt = page1[:16]
    enc_key = bytes.fromhex(enc_key_hex)
    return any(_page1_mac_ok(enc_key, page1, var, salt) for var in VARIANTS)


# ---------------------------------------------------------------- 解密

def _derive_aes_key(enc_key: bytes, salt: bytes, var: _Variant) -> bytes:
    if var.kdf == "raw":
        return enc_key
    if var.kdf == "pbkdf2_sha512_256000":
        return hashlib.pbkdf2_hmac("sha512", enc_key, salt, 256000, dklen=32)
    return hashlib.pbkdf2_hmac("sha1", enc_key, salt, 64000, dklen=32)


def _decrypt_page(page: bytes, pgno: int, aes_key: bytes, var: _Variant) -> bytes:
    reserve = var.iv_sz + var.hmac_sz
    iv = page[4096 - reserve : 4096 - reserve + var.iv_sz]
    start = 16 if pgno == 1 else 0
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    plain = cipher.decrypt(page[start : 4096 - reserve])
    if pgno == 1:
        return SQLITE_HDR + plain + b"\x00" * reserve
    return plain + b"\x00" * reserve


def decrypt_database(db_path: str, out_path: str, enc_key_hex: str, log=lambda m: None) -> dict:
    """解密单个数据库（含 -wal 帧合并）。返回 {'ok': bool, 'variant': str, 'pages': int, 'error': str|None}"""
    try:
        with open(db_path, "rb") as fh:
            page1 = fh.read(4096)
    except OSError as e:
        return {"ok": False, "variant": "", "pages": 0, "error": f"读取失败: {e}"}

    if page1[:16] == SQLITE_HDR:
        # 本来就是明文库（未加密账号），连同 wal 一起复制（原子写）
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        tmp_out = out_path + ".tmp"
        with open(db_path, "rb") as fi, open(tmp_out, "wb") as fo:
            while True:
                chunk = fi.read(1024 * 1024)
                if not chunk:
                    break
                fo.write(chunk)
        _merge_plain_wal(db_path, tmp_out)
        os.replace(tmp_out, out_path)
        return {"ok": True, "variant": "plain-copy", "pages": 0, "error": None}

    if len(page1) < 4096:
        return {"ok": False, "variant": "", "pages": 0, "error": "文件过小"}

    salt = page1[:16]
    enc_key = bytes.fromhex(enc_key_hex)

    var_used = None
    for var in VARIANTS:
        if _page1_mac_ok(enc_key, page1, var, salt):
            var_used = var
            break
    if var_used is None:
        return {"ok": False, "variant": "", "pages": 0, "error": "HMAC 校验失败（密钥不匹配）"}

    aes_key = _derive_aes_key(enc_key, salt, var_used)
    reserve = var_used.iv_sz + var_used.hmac_sz

    size = os.path.getsize(db_path)
    main_pages_count = max(1, size // 4096)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    pages = 0
    # 原子写：解密到临时文件再 os.replace，避免与读取并发导致 malformed
    tmp_out = out_path + ".tmp"
    try:
        with open(db_path, "rb") as fi, open(tmp_out, "wb") as fo:
            pgno = 1
            while True:
                page = fi.read(4096)
                if not page:
                    break
                if len(page) < 4096:
                    page = page + b"\x00" * (4096 - len(page))
                fo.write(_decrypt_page(page, pgno, aes_key, var_used))
                pages = pgno
                pgno += 1

        # 合并 -wal：最近未 checkpoint 的消息在 wal 里，不合并会丢数据
        wal_path = db_path + "-wal"
        if os.path.isfile(wal_path) and os.path.getsize(wal_path) > 32:
            n = _merge_wal(wal_path, tmp_out, aes_key, var_used, log)
            if n:
                log(f"    {os.path.basename(db_path)}: 合并 wal 帧 {n} 页")
        os.replace(tmp_out, out_path)
    except Exception as e:
        try:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        except OSError:
            pass
        return {"ok": False, "variant": var_used.name, "pages": pages, "error": f"解密写入失败: {e}"}

    log(f"    {os.path.basename(db_path)}: {pages}/{main_pages_count} 页, 参数 {var_used.name}")
    return {"ok": True, "variant": var_used.name, "pages": pages, "error": None}


def _merge_wal(wal_path: str, out_path: str, aes_key: bytes, var: _Variant, log) -> int:
    """解密 -wal 帧并合并进已解密的主库文件。返回应用的有效帧页数。

    WCDB 修改了 WAL 帧头语义：每代写入的帧内 salt 标签与文件头不一致。
    代际关系沿用标准 WAL 行为：重置后从帧 0 开始覆写，因此**文件头部第一组
    连续相同 salt 的帧是当前代**，其后是历代残留；组内最后一个 commit 帧
    之前（含）为已提交数据。
    """
    with open(wal_path, "rb") as f:
        data = f.read()
    if len(data) < 32 + 4120:
        return 0
    magic = int.from_bytes(data[0:4], "big")
    if magic not in (0x377F0682, 0x377F0683):
        return 0
    if int.from_bytes(data[8:12], "big") != 4096:
        return 0

    frame_sz = 24 + 4096
    n = (len(data) - 32) // frame_sz

    def frame_salt(i: int) -> tuple[bytes, bytes]:
        off = 32 + i * frame_sz
        return data[off + 8: off + 12], data[off + 12: off + 16]

    # 第一组 = 当前代
    end = 0
    gkey = frame_salt(0)
    while end < n and frame_salt(end) == gkey:
        end += 1

    last_commit_idx = -1
    db_size_pages = 0
    for i in range(0, end):
        commit = int.from_bytes(data[32 + i * frame_sz + 4: 32 + i * frame_sz + 8], "big")
        if commit:
            last_commit_idx = i
            db_size_pages = commit
    if last_commit_idx < 0:
        return 0  # 当前代没有已提交事务，主库已是最新

    latest: dict[int, bytes] = {}
    for i in range(0, last_commit_idx + 1):
        off = 32 + i * frame_sz
        fh = data[off: off + 24]
        pgno = int.from_bytes(fh[0:4], "big")
        if pgno < 1:
            break
        pg = data[off + 24: off + 24 + 4096]
        try:
            latest[pgno] = _decrypt_page(pg, pgno, aes_key, var)
        except Exception:
            break

    if not latest:
        return 0

    with open(out_path, "r+b") as fo:
        fo.seek(0, os.SEEK_END)
        cur_pages = fo.tell() // 4096
        target = max(cur_pages, max(latest), db_size_pages or 0)
        if db_size_pages and target < cur_pages:
            fo.truncate(db_size_pages * 4096)
            cur_pages = db_size_pages
            target = max(cur_pages, max(latest))
        if target > cur_pages:
            fo.seek(cur_pages * 4096)
            fo.write(b"\x00" * ((target - cur_pages) * 4096))
        for pgno, page in latest.items():
            fo.seek((pgno - 1) * 4096)
            fo.write(page)
    return len(latest)


def _merge_plain_wal(db_path: str, out_path: str) -> None:
    """明文库复制场景：wal 本身未加密，按标准 WAL 语义合并页帧。"""
    wal_path = db_path + "-wal"
    if not os.path.isfile(wal_path) or os.path.getsize(wal_path) <= 32:
        return
    try:
        with open(wal_path, "rb") as f:
            data = f.read()
        if int.from_bytes(data[0:4], "big") not in (0x377F0682, 0x377F0683):
            return
        if int.from_bytes(data[8:12], "big") != 4096:
            return
        salt1, salt2 = data[16:20], data[20:24]
        latest: dict[int, bytes] = {}
        db_size_pages = 0
        off, frame_sz = 32, 24 + 4096
        while off + frame_sz <= len(data):
            fh = data[off: off + 24]
            pgno = int.from_bytes(fh[0:4], "big")
            commit = int.from_bytes(fh[4:8], "big")
            if fh[8:12] != salt1 or fh[12:16] != salt2:
                break
            latest[pgno] = data[off + 24: off + 24 + 4096]
            if commit:
                db_size_pages = commit
            off += frame_sz
        if not latest:
            return
        with open(out_path, "r+b") as fo:
            fo.seek(0, os.SEEK_END)
            cur = fo.tell() // 4096
            target = max(cur, max(latest), db_size_pages or 0)
            if target > cur:
                fo.seek(cur * 4096)
                fo.write(b"\x00" * ((target - cur) * 4096))
            for pgno, page in latest.items():
                fo.seek((pgno - 1) * 4096)
                fo.write(page)
    except Exception:
        pass
