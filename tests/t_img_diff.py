# -*- coding: utf-8 -*-
"""决定性实验：逐字节对比多个 V2 文件头部，定位真实字段偏移与数据起点。"""
import os

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"

files = []
for root, _d, fl in os.walk(attach):
    for f in fl:
        if not f.endswith(".dat"):
            continue
        p = os.path.join(root, f)
        try:
            with open(p, "rb") as fh:
                d = fh.read(2048)
        except OSError:
            continue
        if d[:6] == V2:
            files.append((f, d))
        if len(files) >= 12:
            break

out = []
out.append(f"对比 {len(files)} 个文件的前 2048 字节\n")

base_name, base = files[0]
out.append(f"基准: {base_name}\n")

# 逐字节：多少文件在该偏移上取值相同
same = []
for off in range(2048):
    vals = {d[off] for _n, d in files}
    if len(vals) == 1:
        same.append(off)
    else:
        break
out.append(f"前 {len(same)} 字节在所有文件中完全相同（偏移 0..{len(same)-1}）")
out.append(f"  这段 hex: {base[:len(same)].hex()}")
out.append(f"  从偏移 {len(same)} 开始出现差异\n")

# 显示基准文件偏移 0..160 的详细解析
out.append("基准文件前 160 字节逐段解析:")
for i in range(0, 160, 16):
    chunk = base[i:i + 16]
    out.append(f"  [{i:4d}] {chunk.hex()}  {chunk!r}")

# 差异区段里，各文件的前 32 字节（AES区起始）
out.append("\n各文件偏移 15..79 的内容（若相同说明是固定头）:")
for n, d in files[:12]:
    out.append(f"  {n[:40]:42s} {d[15:47].hex()}")

# 关键：统计整个文件里 0xb7 连续出现的模式（XOR 填充）
out.append("\n检查 '?'(0x3f, 即明文0xb7 xor 0x88) 的分布:")
for n, d in files[:6]:
    cnt = d.count(0x3f)
    out.append(f"  {n[:40]:42s} 0x3f出现 {cnt} 次 / {len(d)}")

with open("out_tmp9.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out))