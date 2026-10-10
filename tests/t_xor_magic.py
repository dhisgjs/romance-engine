# -*- coding: utf-8 -*-
"""检查 XOR 区（异或0x88后）是否含 JPEG/PNG 魔数的异或形态。

JPEG 魔数 ffd8ff ^ 88 88 88 = 775077
PNG   魔数 89504e ^ 88 88 88 = 01d8c6
BMP   魔数 424d   ^ 88 88   = ca c5
"""
import os
from collections import Counter

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"
XOR_KEY = 0x88

# 异或形态的魔数
XOR_MAGICS = {
    bytes(b ^ XOR_KEY for b in b"\xff\xd8\xff"): "jpeg",
    bytes(b ^ XOR_KEY for b in b"\x89PNG"): "png",
    bytes(b ^ XOR_KEY for b in b"GIF8"): "gif",
    bytes(b ^ XOR_KEY for b in b"BM"): "bmp",
    bytes(b ^ XOR_KEY for b in b"RIFF"): "riff",
}

out = []
total = hit = 0
examples = []
for r, _d, fl in os.walk(attach):
    for f in fl:
        if not f.endswith(".dat"):
            continue
        p = os.path.join(r, f)
        try:
            with open(p, "rb") as fh:
                d = fh.read()
        except OSError:
            continue
        if d[:6] != V2:
            continue
        x = int.from_bytes(d[10:14], "little")
        if x <= 0 or x > len(d):
            continue
        xz = bytes(b ^ XOR_KEY for b in d[-x:])
        total += 1
        for xmagic, name in XOR_MAGICS.items():
            i = xz.find(xmagic)
            if i >= 0:
                hit += 1
                if len(examples) < 5:
                    examples.append(f"{f[:50]} XOR+{i} {name} 魔数异或形态 {xmagic.hex()}")
                break
    if total > 800:
        break

text = f"扫描 {total} 个文件，XOR区异或0x88后含魔数: {hit}\n" + "\n".join(examples)
with open("out_tmp33.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)