# -*- coding: utf-8 -*-
"""检查 AES 区(1024B)之后的数据是否直接是图片（绕过密钥）。"""
import os

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"
MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")

out = []
files = []
for r, _d, fl in os.walk(attach):
    for f in fl:
        if f.endswith(".dat"):
            files.append(os.path.join(r, f))
    if len(files) > 400:
        break

# 统计 AES 区后各偏移处的字节分布（是否像图片数据 or 填充）
from collections import Counter
pos_counters = {}
for p in files[:400]:
    try:
        with open(p, "rb") as fh:
            data = fh.read(1200)
    except OSError:
        continue
    if data[:6] != V2:
        continue
    for off in (1024, 1039, 1054, 1070, 1100, 1150):
        if off < len(data):
            pos_counters.setdefault(off, Counter())[data[off]] += 1

for off in sorted(pos_counters):
    c = pos_counters[off]
    top = c.most_common(5)
    out.append(f"偏移{off}: 最常见字节 {[(hex(b), n) for b, n in top]} (共{sum(c.values())})")

# 找一个文件，打印 1024..1200 的内容
p0 = files[0]
with open(p0, "rb") as fh:
    d = fh.read(1400)
if d[:6] == V2:
    out.append(f"\n样例 {os.path.basename(p0)}:")
    out.append(f"  [1024:1080] {d[1024:1080].hex()}")
    out.append(f"  [1024:1080] {d[1024:1080]!r}")
    out.append(f"  整段 [1024:] 找魔数:")
    for m in MAGICS:
        i = d[1024:].find(m)
        if i >= 0:
            out.append(f"    {m} @ 偏移{1024+i}")

text = "\n".join(out)
with open("out_tmp27.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)