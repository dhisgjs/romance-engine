# -*- coding: utf-8 -*-
"""验证 decrypt_v2_bytes 的 unpad 是否是失败原因，并试多种拼接方式。"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress
from backend.core.media import detect_format
from Crypto.Cipher import AES

root = "data/decrypted/wxid_your_account_efcf"
acc = "wxid_your_account_efcf"
src = rf"D:\personal\Documents\xwechat_files\{acc}"
attach = os.path.join(src, "msg", "attach")
V2 = b"\x07\x08V2\x08\x07"


def aligned(size):
    return size - (~size % 16)


def try_decrypt(data, key, mode):
    """mode: 拼接策略"""
    a = int.from_bytes(data[6:10], "little")
    x = int.from_bytes(data[10:14], "little")
    al = aligned(a)
    aes_zone = data[15:15 + al]
    if len(aes_zone) % 16:
        aes_zone = aes_zone[:len(aes_zone) - len(aes_zone) % 16]
    if not aes_zone:
        return None
    c = AES.new(key, AES.MODE_ECB)
    dec_aes = c.decrypt(aes_zone)
    raw_end = len(data) - x
    raw = data[15 + al: raw_end] if 15 + al < raw_end else b""
    xor_part = bytes(b ^ 0x88 for b in data[raw_end:])
    if mode == "nopad":          # 不用 unpad，全用
        plain = dec_aes + raw + xor_part
    elif mode == "rawfirst":     # raw 在前
        plain = raw + dec_aes + xor_part
    elif mode == "noXor":        # xor 部分不处理
        plain = dec_aes + raw
    elif mode == "onlyAes":      # 只有 AES 部分
        plain = dec_aes
    else:
        return None
    fmt = detect_format(plain)
    return (fmt, len(plain)) if fmt != "bin" else None


# 取样本
disk = {}
for r, _d, files in os.walk(attach):
    for f in files:
        if f.endswith(".dat"):
            disk.setdefault(re.sub(r"_([th])\.dat$", "", f)[:-4].lower(), []).append(os.path.join(r, f))

hl = os.path.join(root, "hardlink", "hardlink.db")
c = sqlite3.connect("file:" + hl.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
dir2id = {rid: u for rid, u in c.execute("SELECT rowid, username FROM dir2id")}
hl_map = {}
for md5, fname, d1, d2 in c.execute("SELECT md5, file_name, dir1, dir2 FROM image_hardlink_info_v4"):
    if fname and fname != "0":
        hl_map.setdefault(md5.lower(), []).append((fname, d1, d2))
c.close()

samples = []
msg_dir = os.path.join(root, "message")
for fn in sorted(os.listdir(msg_dir)):
    if not fn.endswith(".db"):
        continue
    p = os.path.join(msg_dir, fn).replace("\\", "/")
    try:
        cc = sqlite3.connect("file:" + p + "?mode=ro", uri=True)
        cc.text_factory = lambda b: b.decode("utf-8", errors="replace")
        _tabs = [r[0] for r in cc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
    except Exception:
        continue
    for t in _tabs:
        cols = [r[1] for r in cc.execute('PRAGMA table_info("' + t + '")')]
        if "message_content" not in cols:
            continue
        for mc, ccx, ct in cc.execute(
                'SELECT message_content, compress_content, WCDB_CT_message_content FROM "' + t + '" LIMIT 300'):
            try:
                content = wcdb_decompress(mc or ccx, ct)
            except Exception:
                continue
            if content and "<img" in content:
                m = re.search(r'md5="([0-9a-fA-F]{32})"', content)
                k = re.search(r'aeskey="([0-9a-fA-F]{32})"', content)
                if m and k:
                    md5 = m.group(1).lower()
                    for cand in disk.get(md5, []):
                        samples.append((md5, k.group(1).lower(), cand))
                    for fname, d1, d2 in hl_map.get(md5, []):
                        pth = os.path.join(attach, str(dir2id.get(d1, "?")), str(dir2id.get(d2, "?")), "Img", fname)
                        if os.path.isfile(pth):
                            samples.append((md5, k.group(1).lower(), pth))
    cc.close()
    if len(samples) >= 300:
        break

print(f"样本 {len(samples)}")
stats = {}
examples = []
for md5, aeshex, pth in samples:
    try:
        with open(pth, "rb") as fh:
            data = fh.read()
    except OSError:
        continue
    if data[:6] != V2:
        continue
    for keyname, key in (
        ("hex16", bytes.fromhex(aeshex)),
        ("hex32", bytes.fromhex(aeshex) * 2),
        ("asc32", aeshex.encode("latin-1")[:32]),
    ):
        for mode in ("nopad", "rawfirst", "noXor", "onlyAes"):
            k = (keyname, mode)
            stats.setdefault(k, 0)
            r = try_decrypt(data, key[:16] if len(key) >= 16 else key, mode)
            if r:
                stats[k] += 1
                if len(examples) < 10:
                    examples.append(f"OK md5={md5[:10]} {k} -> {r}")
                break

text = "\n".join(f"{k}: {v}" for k, v in sorted(stats.items(), key=lambda x: -x[1])) + "\n\n" + "\n".join(examples)
with open("out_tmp26.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)