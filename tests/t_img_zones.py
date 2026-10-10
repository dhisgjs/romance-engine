# -*- coding: utf-8 -*-
"""检查 V2 文件三段结构：AES区 / raw区 / XOR区，确认格式假设。"""
import os
from Crypto.Cipher import AES

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"
MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")


def is_img(d: bytes) -> bool:
    return any(d.startswith(m) for m in MAGICS) or (d[:4] == b"RIFF" and d[8:12] == b"WEBP")


out = []
# 挑一个小原图（全文件小，便于完整分析）
target = None
for root, _d, fl in os.walk(attach):
    for f in fl:
        if f.endswith(".dat") and not f.endswith(("_t.dat", "_h.dat")):
            p = os.path.join(root, f)
            if target is None or os.path.getsize(p) < target[0]:
                target = (os.path.getsize(p), p)
# 两个：最小和一个中间大小
small = target
mid = None
for root, _d, fl in os.walk(attach):
    for f in fl:
        if f.endswith(".dat") and not f.endswith(("_t.dat", "_h.dat")):
            p = os.path.join(root, f)
            sz = os.path.getsize(p)
            if 50000 < sz < 100000:
                mid = (sz, p)
                break
    if mid:
        break

for label, (sz, p) in (("最小", small), ("中", mid)):
    with open(p, "rb") as fh:
        d = fh.read()
    if d[:6] != V2:
        continue
    a = int.from_bytes(d[6:10], "little")
    x = int.from_bytes(d[10:14], "little")
    aes_end = 15 + ((a + 15) // 16 * 16)   # aligned aes end
    raw_end = len(d) - x                     # raw 区结束
    aes_zone = d[15:aes_end]
    raw_zone = d[aes_end:raw_end]
    xor_zone = d[raw_end:]
    xor_dec = bytes(b ^ 0x88 for b in xor_zone)
    out.append(f"=== {label} {os.path.basename(p)} size={sz} aes={a} xor={x}")
    out.append(f"  AES区前16 hex: {aes_zone[:16].hex()} len={len(aes_zone)}")
    out.append(f"  raw区: len={len(raw_zone)} 前16hex={raw_zone[:16].hex()} 可读={raw_zone[:32]!r}")
    out.append(f"     raw区is_img开头: {is_img(raw_zone)}")
    out.append(f"     raw区内 FFD8/FFD9/IEND 位置: FFD8@{raw_zone.find(b'\\xff\\xd8')} FFD9@{raw_zone.find(b'\\xff\\xd9')} PNG@{raw_zone.find(b'\\x89PNG')}")
    out.append(f"  XOR区: len={len(xor_zone)} 解密后前16hex={xor_dec[:16].hex()} is_img={is_img(xor_dec)}")
    out.append(f"     XOR FFD8位置: {xor_dec.find(b'\\xff\\xd8')}")

with open("out_tmp5.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))