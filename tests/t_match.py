# -*- coding: utf-8 -*-
"""用内存 JPEG 明文的 md5/特征 匹配磁盘 .dat（.dat 文件名就是原图 md5）。"""
import hashlib
import os
import re

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"

# 磁盘上所有 .dat 文件名（不含 _t/_h）
disk = {}
for r, _d, files in os.walk(attach):
    for f in files:
        if not f.endswith(".dat"):
            continue
        base = os.path.splitext(f)[0].lower()
        keyname = re.sub(r"_(t|h)$", "", base)
        if len(keyname) == 32:
            disk.setdefault(keyname, []).append(os.path.join(r, f))

print(f"磁盘唯一图片名: {len(disk)}")

# 内存 JPEG 的 md5
mem_files = [f for f in os.listdir("tests") if f.startswith("memimg_") and f.endswith(".jpg")]
out = []
for mf in mem_files:
    with open(os.path.join("tests", mf), "rb") as fh:
        data = fh.read()
    md5 = hashlib.md5(data).hexdigest()
    out.append(f"{mf}: size={len(data)} md5={md5} 匹配={'HIT' if md5 in disk else 'no'}")
    if md5 in disk:
        for p in disk[md5]:
            out.append(f"    -> {p}")

text = "\n".join(out)
with open("out_match.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)