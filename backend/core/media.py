# -*- coding: utf-8 -*-
"""图片 / 表情包解密与定位。

图片（type 3）：
    消息XML md5 → hardlink.db image_hardlink_info_v4 (md5→file_name/dir1/dir2)
    → dir2id 表还原路径 attach/<talker_md5>/<YYYY-MM>/Img/<file_name>
    → V2 格式解密：头15字节(magic6+aes_size4+xor_size4+pad1) +
      [AES-128-ECB aligned(aes_size)] + [raw] + [xor_size ⊕ 0x88]
    密钥为 16 字节 ASCII，存于微信进程内存（看过图后才有），需已知明文攻击提取。

表情包（type 47）：
    XML md5 → emoticon.db kNonStoreEmoticonTable.aes_key
    → business/emoticon/Persist/<md5[:2]>/<md5>，AES-128-ECB(PKCS7) 解密。
"""
from __future__ import annotations

import os
import re
import sqlite3
import time

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

V2_MAGIC = b"\x07\x08V2\x08\x07"
V1_MAGIC = b"\x07\x08V1\x08\x07"
V1_KEY = b"cfcd208495d565ef"
XOR_KEY = 0x88

MAGICS = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG", "png"),
    (b"GIF8", "gif"),
    (b"BM", "bmp"),
    (b"wxgf", "hevc"),
)

# 浏览器无法直接显示的格式。wxgf 是微信自研容器，无标准解码路径。
NEEDS_CONVERT = {"hevc"}


def convert_to_jpeg(data: bytes) -> bytes | None:
    """把浏览器不认的格式转成 JPEG。wxgf 无法转换（微信自研容器），返回 None。"""
    try:
        import io

        from PIL import Image
    except ImportError:
        return None
    try:
        import pillow_heif  # noqa: F401

        pillow_heif.register_heif_opener()
    except Exception:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    except Exception:
        return None

# 密钥验证阈值：单样本或低命中率会出现假阳性（不同文件的缩略图首块会重复）
MIN_SAMPLES = 5
MIN_HIT_RATE = 0.9


def detect_format(data: bytes) -> str:
    for magic, name in MAGICS:
        if data.startswith(magic):
            return name
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"II*\x00" or data[:4] == b"MM\x00*":
        return "tif"
    return "bin"


def _aligned(size: int) -> int:
    return size - ~(~size % 16)


def _read_head(path: str, n: int = 32) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def decrypt_v2_bytes(data: bytes, key: bytes) -> tuple[bytes, str] | None:
    """解密 V1/V2 格式 .dat 内容，返回 (明文, 格式) 或 None。"""
    if len(data) < 15:
        return None
    sig = data[:6]
    if sig == V2_MAGIC:
        aes_key = key
    elif sig == V1_MAGIC:
        aes_key = V1_KEY
    else:
        return None
    aes_size = int.from_bytes(data[6:10], "little")
    xor_size = int.from_bytes(data[10:14], "little")
    aligned = _aligned(aes_size)
    if 15 + aligned > len(data) or len(aes_key) < 16:
        return None
    try:
        cipher = AES.new(aes_key[:16], AES.MODE_ECB)
        dec_aes = unpad(cipher.decrypt(data[15:15 + aligned]), 16)
    except Exception:
        return None
    raw_end = len(data) - xor_size
    raw = data[15 + aligned: raw_end] if 15 + aligned < raw_end else b""
    xor_part = bytes(b ^ XOR_KEY for b in data[raw_end:])
    plain = dec_aes + raw + xor_part
    fmt = detect_format(plain)
    if fmt == "bin":
        return None
    return plain, fmt


def decrypt_legacy_bytes(data: bytes) -> tuple[bytes, str] | None:
    """旧版全文件 XOR：密钥由文件头与图片魔数异或推断。"""
    if len(data) < 4:
        return None
    for magic, _name in MAGICS:
        key = data[0] ^ magic[0]
        if all((data[i] ^ key) == magic[i] for i in range(min(len(magic), len(data)))):
            plain = bytes(b ^ key for b in data)
            fmt = detect_format(plain)
            if fmt != "bin":
                return plain, fmt
    return None


def decrypt_sticker_bytes(data: bytes, keys: list[bytes]) -> tuple[bytes, str] | None:
    """表情包 Persist 文件：AES-128-ECB(PKCS7)，依次尝试表情 aes_key 与全局图片密钥。"""
    if len(data) == 0 or len(data) % 16:
        return None
    for key in keys:
        if not key or len(key) < 16:
            continue
        try:
            cipher = AES.new(key[:16], AES.MODE_ECB)
            raw = cipher.decrypt(data)
        except Exception:
            continue
        for candidate in _unpad_variants(raw):
            fmt = detect_format(candidate)
            if fmt != "bin":
                return candidate, fmt
    return None


def _unpad_variants(raw: bytes):
    """PKCS7 去填充 + 原文两种候选。"""
    try:
        yield unpad(raw, 16)
    except Exception:
        pass
    yield raw


class MediaStore:
    """一个账号的媒体定位与解密。"""

    def __init__(self, account: str, decrypted_root: str, keys_dir: str, source_base: str | None):
        self.account = account
        self.decrypted_root = decrypted_root
        self.keys_dir = keys_dir
        self.source_base = source_base  # xwechat_files/<acc> 目录（含 msg\attach、business）
        self._hl_map: dict[str, list[tuple[str, int, int]]] | None = None
        self._dir2id: dict[int, str] | None = None
        self._sticker_keys: dict[str, str] | None = None
        self._cache_map: dict[str, tuple[str, str]] | None = None  # md5 -> (path, kind)
        self._cache_refresh_at = 0.0

    # ---- 路径 ----

    def _open(self, rel: str) -> sqlite3.Connection | None:
        p = os.path.join(self.decrypted_root, self.account, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            return None
        conn = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        return conn

    def _open_live(self, rel: str) -> sqlite3.Connection | None:
        """打开消息库（可能带 WAL），不能用 immutable —— 会读到过期快照。"""
        p = os.path.join(self.decrypted_root, self.account, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            return None
        try:
            conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        except sqlite3.Error:
            return None
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        return conn

    def image_key(self) -> bytes | None:
        p = os.path.join(self.keys_dir, f"{self.account}.image_key")
        if os.path.isfile(p):
            try:
                with open(p) as f:
                    k = f.read().strip()
                if len(k) == 32:
                    return bytes.fromhex(k)
            except Exception:
                return None
        return None

    def _ensure_hardlink(self) -> bool:
        if self._hl_map is not None:
            return True
        conn = self._open("hardlink/hardlink.db")
        if conn is None:
            return False
        try:
            self._dir2id = {rid: u for rid, u in conn.execute("SELECT rowid, username FROM dir2id")}
            self._hl_map = {}
            for md5, fname, d1, d2 in conn.execute(
                "SELECT md5, file_name, dir1, dir2 FROM image_hardlink_info_v4"
            ):
                self._hl_map.setdefault(md5.lower(), []).append((fname, d1, d2))
            return True
        except Exception:
            self._hl_map = {}
            return False
        finally:
            conn.close()

    def _ensure_emoticon(self) -> bool:
        if self._sticker_keys is not None:
            return True
        self._sticker_keys = {}
        conn = self._open("emoticon/emoticon.db")
        if conn is None:
            return False
        try:
            for md5, aes in conn.execute("SELECT md5, aes_key FROM kNonStoreEmoticonTable"):
                if md5 and aes:
                    self._sticker_keys[md5.lower()] = aes
        except Exception:
            pass
        finally:
            conn.close()
        return True

    # ---- 解析 ----

    def resolve_image(self, md5: str, variant: str = "t") -> str | None:
        """返回加密 .dat 源文件路径。variant: t=缩略图优先, full=原图优先。"""
        if not self._ensure_hardlink() or not self.source_base:
            return None
        md5 = md5.lower()
        recs = self._hl_map.get(md5) or []
        # 收集该 md5 的所有文件名（含 _h/_t 变体行 + 本行派生）
        names = {fname for fname, _d1, _d2 in recs if fname and fname != "0"}
        for fname, d1, d2 in recs:
            if fname and fname != "0":
                base = re.sub(r"_(h|t)\.dat$", ".dat", fname)
                if variant == "t":
                    names.add(base.replace(".dat", "_t.dat"))
                else:
                    names.update([base, base.replace(".dat", "_h.dat")])
        # 排序：t 变体优先（缩略图），full 时原图 > _h > _t
        def rank(n: str) -> int:
            if variant == "t":
                return 0 if n.endswith("_t.dat") else (1 if n.endswith("_h.dat") else 2)
            return 0 if not n.endswith(("_t.dat", "_h.dat")) else (1 if n.endswith("_h.dat") else 2)

        for fname, d1, d2 in sorted(recs, key=lambda r: rank(r[0])):
            for n in [fname] + sorted(names, key=rank):
                if not n or n == "0":
                    continue
                d = os.path.join(
                    self.source_base, "msg", "attach",
                    self._dir2id.get(d1, "?"), self._dir2id.get(d2, "?"), "Img", n,
                )
                if os.path.isfile(d):
                    return d
        return None

    def resolve_sticker(self, md5: str) -> str | None:
        if not self.source_base:
            return None
        p = os.path.join(self.source_base, "business", "emoticon", "Persist", md5[:2].lower(), md5.lower())
        return p if os.path.isfile(p) else None

    def _ensure_cache(self) -> bool:
        """索引 cache 下的明文图片：md5 -> (path, kind)。

        cache/<月>/Message/<talker_hash>/{Thumb,ImageTemp}/<local_id>_<ts>_<kind>
        这些是微信已渲染过的明文图（缩略图/高清图），无需解密即可显示。
        通过消息表把 (talker_hash, local_id) 反查成 XML 里的 md5。
        """
        if self._cache_map is not None:
            return True
        self._cache_map = {}
        self._cache_refresh_at = time.time() + 3
        if not self.source_base:
            return False
        cache_root = os.path.join(self.source_base, "cache")
        if not os.path.isdir(cache_root):
            return False
        # 收集 (talker_hash, local_id) -> cache 文件
        by_key: dict[tuple[str, int], tuple[str, str]] = {}
        for root, _dirs, files in os.walk(cache_root):
            kind = os.path.basename(root)
            if kind not in ("Thumb", "ImageTemp"):
                continue
            rel = os.path.relpath(root, cache_root).split(os.sep)
            if len(rel) < 3 or rel[1] != "Message":
                continue
            talker_hash = rel[2].lower()
            for f in files:
                m = re.match(r"(\d+)_\d+_[A-Za-z0-9_]+", f)
                if not m:
                    continue
                full = os.path.join(root, f)
                try:
                    if detect_format(_read_head(full)) == "bin":
                        continue
                except OSError:
                    continue
                lid = int(m.group(1))
                # ImageTemp 优先于 Thumb
                prev = by_key.get((talker_hash, lid))
                if prev is None or (kind == "ImageTemp" and prev[1] != "ImageTemp"):
                    by_key[(talker_hash, lid)] = (full, kind)
        if not by_key:
            return True
        # 批量反查 md5
        try:
            from backend.core.models import wcdb_decompress
        except Exception:
            return True
        conn_cache: dict[str, sqlite3.Connection] = {}
        for (talker_hash, lid), (path, kind) in by_key.items():
            rel_db = None
            for db in ("message/message_0.db", "message/biz_message_0.db"):
                if db not in conn_cache:
                    c = self._open_live(db)
                    if c is None:
                        continue
                    conn_cache[db] = c
                c = conn_cache[db]
                try:
                    has = c.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (f"Msg_{talker_hash}",)).fetchone()
                except Exception:
                    has = None
                if has:
                    rel_db = db
                    break
            if rel_db is None:
                continue
            c = conn_cache[rel_db]
            try:
                table_cols = {
                    r[1] for r in c.execute(
                        'PRAGMA table_info("Msg_%s")' % talker_hash)
                }
                ct_cols = [
                    col for col in (
                        "WCDB_CT_message_content",
                        "WCDB_CT_compress_content",
                    ) if col in table_cols
                ]
                selected_ct = ", ".join(ct_cols) if ct_cols else "NULL AS WCDB_CT_message_content"
                row = c.execute(
                    'SELECT message_content, compress_content, ' + selected_ct + ' '
                    'FROM "Msg_%s" WHERE local_id=? AND (local_type & 4294967295)=3' % talker_hash,
                    (lid,)).fetchone()
            except Exception:
                continue
            if not row:
                continue
            if len(ct_cols) == 2:
                mc, cpx, ct, cpx_ct = row
            elif len(ct_cols) == 1:
                mc, cpx, ct = row
                cpx_ct = ct
            else:
                mc, cpx = row
                ct = cpx_ct = None
            try:
                content = wcdb_decompress(mc or cpx, ct or cpx_ct)
            except Exception:
                content = b""
            txt = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
            mm = re.search(r'md5="([0-9a-fA-F]{32})"', txt)
            if mm:
                self._cache_map.setdefault(mm.group(1).lower(), (path, kind))
        for c in conn_cache.values():
            try:
                c.close()
            except Exception:
                pass
        return True

    def resolve_cache_image(self, md5: str) -> str | None:
        """返回 cache 下已缓存的明文图路径（若有），用于免密钥直接显示。"""
        if (self._cache_map is not None and md5.lower() not in self._cache_map
                and time.time() >= self._cache_refresh_at):
            self._cache_map = None
        self._ensure_cache()
        if not self._cache_map:
            return None
        hit = self._cache_map.get(md5.lower())
        return hit[0] if hit else None

    def load_displayable_image(self, md5: str) -> bytes | None:
        """读 cache 明文图；wxgf/hevc 转成 JPEG（桌面 QPixmap 才能显示）。

        返回可直接解码的图片字节（png/jpg/gif/webp/heic→jpg）。无图返回 None。
        """
        path = self.resolve_cache_image(md5)
        if not path:
            return None
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return None
        fmt = detect_format(data[:32])
        if fmt in NEEDS_CONVERT:
            jpg = convert_to_jpeg(data)
            return jpg if jpg else None
        if fmt == "bin":
            return None
        return data

    def sticker_aeskey(self, md5: str) -> str | None:
        self._ensure_emoticon()
        return (self._sticker_keys or {}).get(md5.lower())

    # ---- 解密 ----

    def decrypt_file(self, path: str, sticker_aeskey: str | None = None) -> tuple[bytes, str] | None:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return None
        head = data[:6]
        if head in (V2_MAGIC, V1_MAGIC):
            key = self.image_key()
            if key is None:
                return None
            return decrypt_v2_bytes(data, key)
        # 表情包 Persist 等无头文件：依次尝试 表情aes_key / 全局图片密钥
        keys: list[bytes] = []
        if sticker_aeskey and len(sticker_aeskey) >= 32:
            keys.append(bytes.fromhex(sticker_aeskey[:32]))
        ik = self.image_key()
        if ik:
            keys.append(ik)
        if keys:
            return decrypt_sticker_bytes(data, keys)
        return decrypt_legacy_bytes(data)

    def cache_path(self, md5: str, variant: str, fmt: str) -> str:
        d = os.path.join(self.decrypted_root, "_mediacache", self.account)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{md5}_{variant}.{fmt}")


# ---------------------------------------------------------------- 图片密钥提取

def find_sample_blocks(source_base: str, limit: int = 12) -> list[bytes]:
    """从 attach 目录找 V2 图片的第一个密文块作为已知明文攻击样本。

    收集多个不同文件的密文块（原图优先，缩略图 _t 兜底）并按块内容去重：
    缩略图与高清图用同一媒体密钥加密（V2），但不同文件的同一首块可能重复，
    去重后样本才足够严格，避免单样本验证出假阳性密钥。
    """
    attach = os.path.join(source_base, "msg", "attach")
    blocks: list[bytes] = []
    seen: set[bytes] = set()
    if not os.path.isdir(attach):
        return blocks

    def _collect(suffix_filter):
        for root, _dirs, files in os.walk(attach):
            for f in files:
                if not f.endswith(".dat") or not suffix_filter(f):
                    continue
                p = os.path.join(root, f)
                try:
                    with open(p, "rb") as fh:
                        if fh.read(6) != V2_MAGIC:
                            continue
                        fh.seek(15)
                        blk = fh.read(16)
                except OSError:
                    continue
                if len(blk) == 16 and blk not in seen:
                    seen.add(blk)
                    blocks.append(blk)
                    if len(blocks) >= limit:
                        return True
        return False

    if _collect(lambda f: not f.endswith(("_t.dat", "_h.dat"))):
        return blocks
    _collect(lambda f: f.endswith("_t.dat"))
    return blocks


def try_image_key(candidates: set[str], blocks: list[bytes]) -> str | None:
    """对候选密钥逐一做 AES-ECB 已知明文验证，返回 16 字节密钥（hex str）。

    严格标准：必须解开 >= MIN_SAMPLES 个密文块且命中率 >= MIN_HIT_RATE。
    单样本或低命中率会出现假阳性（缩略图首块在不同文件间会重复）。
    """
    if not blocks or len(blocks) < 3:
        return None
    need = max(MIN_SAMPLES, int(len(blocks) * MIN_HIT_RATE))
    for s in candidates:
        b = s.encode("latin-1", errors="ignore") if isinstance(s, str) else s
        for kb in {b[:16], b[-16:]}:
            if len(kb) != 16:
                continue
            try:
                cipher = AES.new(kb, AES.MODE_ECB)
            except Exception:
                continue
            ok = 0
            for ct in blocks:
                try:
                    dec = cipher.decrypt(ct)
                except Exception:
                    break
                if detect_format(dec) != "bin":
                    ok += 1
            if ok >= need:
                return kb.hex()
    return None
