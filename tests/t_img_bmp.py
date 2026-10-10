# -*- coding: utf-8 -*-
"""完整解密一个 V2 文件：XOR 区就是 BMP 图片数据，确定 XOR key 与格式。"""
import os

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"

# 找到 13cb315d930d72c83159dca139f234a0.dat（非缩略图）
target = None
for root, _d, fl in os.walk(attach):
    for f in fl:
        if f == "13cb315d930d72c83159dca139f234a0.dat":
            target = os.path.join(root, f)
            break
    if target:
        break
out = []
if not target:
    out.append("未找到目标文件")
else:
    out.append(f"目标: {target}")
    with open(target, "rb") as fh:
        d = fh.read()
    a = int.from_bytes(d[6:10], "little")
    x = int.from_bytes(d[10:14], "little")
    out.append(f"size={len(d)} aes={a} xor={x}")
    xor_zone = d[-x:]

    # 1) 原始 xor_zone 是否含 BM？
    i = xor_zone.find(b"BM")
    out.append(f"原始 XOR区 find BM: {i}")
    if i >= 0:
        bmp = xor_zone[i:]
        out.append(f"BMP 大小: {len(bmp)}")
        out.append(f"BMP 头54: {bmp[:54].hex()}")
        out.append(f"BMP 宽高: {int.from_bytes(bmp[18:22],'little')}x{int.from_bytes(bmp[22:26],'little')}")

    # 2) 哪些 XOR key 能让 XOR区开头命中图片魔数？
    out.append(f"XOR区前32 hex: {xor_zone[:32].hex()}")
    out.append(f"XOR区前64 可读: {xor_zone[:64]!r}")
    for magic, name in ((b"BM", "bmp"), (b"\xff\xd8\xff", "jpg"), (b"\x89PNG", "png"), (b"GIF8", "gif")):
        k = xor_zone[0] ^ magic[0]
        dec = bytes(b ^ k for b in xor_zone)
        if dec.startswith(magic):
            out.append(f"XOR key=0x{k:02x} 使开头= {name} !!")

    # 3) 整个文件（含AES区）里找 BM（可能部分未异或）
    pos = d.find(b"BM")
    out.append(f"整个文件 find BM: {pos}")

with open("out_tmp7.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out))