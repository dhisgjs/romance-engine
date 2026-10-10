# -*- coding: utf-8 -*-
"""在 XOR 区找真正的图片数据：尝试不同 XOR key，找 JPEG/PNG 魔数。"""
import os
from Crypto.Cipher import AES

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"
MAGICS = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG", "png"), (b"GIF8", "gif"), (b"RIFF", "riff"), (b"BM", "bmp"), (b"wxgf", "hevc"))


def is_img(d: bytes) -> bool:
    return any(d.startswith(m) for m in MAGICS) or (d[:4] == b"RIFF" and d[8:12] == b"WEBP")


def find_img_in(xor_zone: bytes) -> str | None:
    """在 XOR 区内滑窗找图片魔数（未加密 raw 部分可能直接是图片）。"""
    for m, name in MAGICS:
        i = xor_zone.find(m)
        if i >= 0:
            return name
    # 也看反异或后
    for k in range(256):
        dec = bytes(b ^ k for b in xor_zone)
        for m, name in MAGICS:
            if dec.find(m) >= 0:
                return f"{name}(xor={k})"
    return None


out = []
# 检查多个不同文件
cnt = 0
for root, _d, fl in os.walk(attach):
    for f in fl:
        if not f.endswith(".dat") or f.endswith(("_t.dat", "_h.dat")):
            continue
        p = os.path.join(root, f)
        with open(p, "rb") as fh:
            d = fh.read(31)
        if d[:6] != V2:
            continue
        x = int.from_bytes(d[10:14], "little")
        if x <= 0 or x > 100000:
            continue
        with open(p, "rb") as fh:
            full = fh.read()
        xor_zone = full[-x:]
        r = find_img_in(xor_zone)
        if r:
            out.append(f"{f[:50]}: XOR区({x}B) 发现图片: {r}")
            cnt += 1
        if cnt >= 5:
            break
    if cnt >= 5:
        break

if not out:
    out.append("在 XOR 区内（直接或反异或）没找到任何图片魔数")

# 另外：取一个完整文件，把整个文件（含AES区）按滑窗找 FF D8（可能AES区解密后是jpeg）
# 检查 AES 区 + raw 区能否找到
for root, _d, fl in os.walk(attach):
    for f in fl:
        if f.endswith(".dat") and not f.endswith(("_t.dat", "_h.dat")):
            p = os.path.join(root, f)
            with open(p, "rb") as fh:
                full = fh.read()
            if full[:6] == V2:
                # 全文件找 FFD8 / FFD9
                out.append(f"{f[:40]}: 全文件 FFD8@{full.find(b'\\xff\\xd8')} FFD9@{full.find(b'\\xff\\xd9')} PNG@{full.find(b'\\x89PNG')} size={len(full)}")
                break

with open("out_tmp6.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))