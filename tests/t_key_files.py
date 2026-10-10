# -*- coding: utf-8 -*-
"""磁盘搜索：查找微信可能存放图片密钥的文件（config/缓存/资源）。"""
import os

base = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
found = []
scanned = 0
for root, dirs, files in os.walk(base):
    # 跳过超大的缓存目录加速
    for f in files:
        p = os.path.join(root, f)
        try:
            sz = os.path.getsize(p)
        except OSError:
            continue
        scanned += 1
        # 找可能含 key 的小文件：名字含 key/crypt/media/secret
        low = f.lower()
        if any(k in low for k in ("key", "crypt", "secret", "media_key", "aes", "cipher")):
            found.append((sz, p))

found.sort()
out = [f"扫描 {scanned} 个文件，命中文件名 {len(found)} 个"]
for sz, p in found[:50]:
    rel = os.path.relpath(p, base)
    out.append(f"  {sz:>10}  {rel}")
    try:
        with open(p, "rb") as fh:
            d = fh.read(200)
        out.append(f"      前200字节hex: {d.hex()[:120]}")
        # 尝试找可打印 ASCII
        txt = "".join(chr(c) if 32 <= c < 127 else "." for c in d[:120])
        out.append(f"      ASCII: {txt}")
    except OSError:
        pass

with open("out_tmp10.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out[:60]))