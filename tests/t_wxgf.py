# -*- coding: utf-8 -*-
"""分析 wxgf 容器：找内部是否嵌有 HEIC/ftyp 或裸 HEVC。"""
import os
import re
import sys

SRC = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
p = os.path.join(SRC, "cache", "2026-10", "Message",
                 "812a68e0dfcd495fd77d68ef4f686635", "ImageTemp",
                 "158_1790941059_mid_temp_convert")
d = open(p, "rb").read()
print(f"size={len(d)}")
print(f"head 64: {d[:64].hex()}")
# 搜 ftyp / ftyp brands
for m in re.finditer(b"ftyp", d):
    print(f"  ftyp @{m.start()}: {d[m.start():m.start()+16].hex()} {d[m.start():m.start()+12]!r}")
for m in re.finditer(b"ftyp", d, re.I):
    print(f"  ftyp(i) @{m.start()}: {d[m.start():m.start()+20]!r}")
# 搜 heic/mif1 brands
for brand in (b"heic", b"heix", b"mif1", b"msf1", b"avif"):
    i = d.find(brand)
    if i >= 0:
        print(f"  brand {brand} @{i}")
# 搜 hvcC / hev1 (裸 HEVC)
for tag in (b"hvcC", b"hev1", b"hvc1", b"mdat"):
    i = d.find(tag)
    if i >= 0:
        print(f"  tag {tag} @{i}")
# 搜 PNG/JPEG 魔数
for magic, name in ((b"\xff\xd8\xff", "jpeg"), (b"\x89PNG", "png")):
    for m in re.finditer(re.escape(magic), d):
        print(f"  {name} magic @{m.start()}")
        break
print("前 256 字节可打印:", bytes(b if 32 <= b < 127 else 46 for b in d[:256]))
print("尾部 64:", d[-64:].hex())