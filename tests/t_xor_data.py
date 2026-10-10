# -*- coding: utf-8 -*-
"""验证「交错AES块」假设：XOR 区每隔 1024 字节可能是 AES 块。

V2 可能是：15字节头 + [AES块(16B) | XOR块(1008B)] 重复，即每1024字节一个AES密钥块。
"""
import os
import sys
from collections import Counter

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"

files = []
for r, _d, fl in os.walk(attach):
    for f in fl:
        if f.endswith(".dat"):
            files.append(os.path.join(r, f))
    if len(files) >= 200:
        break

# 对每个文件，XOR 区(解密后)每 16 字节块的统计：是否大量为 b7b7 填充 vs 数据
from Crypto.Cipher import AES

# 关键测试：整个文件按 16B 块切分，检查每块「异或0x88后」是否为 b7 填充
# 若 XOR 区 = [填充 + 真实图片数据]，则数据部分应当是完整的图片（BMP/JPEG）
out = []
# 取大文件（xor 大）
big = []
for p in files:
    sz = os.path.getsize(p)
    if sz > 500000:
        big.append((sz, p))
big.sort(reverse=True)
for sz, p in big[:3]:
    with open(p, "rb") as fh:
        d = fh.read()
    if d[:6] != V2:
        continue
    a = int.from_bytes(d[6:10], "little")
    x = int.from_bytes(d[10:14], "little")
    out.append(f"=== {os.path.basename(p)} size={sz} aes={a} xor={x}")
    # XOR 区解密
    xz = bytes(b ^ 0x88 for b in d[-x:])
    # 统计 0xb7 比例
    b7 = xz.count(0xB7) / len(xz)
    out.append(f"  XOR区 0xb7 占比: {b7:.2%}")
    # 找 XOR 区中的非 b7 片段（真实数据）
    start = None
    segs = []
    for i in range(len(xz)):
        if xz[i] != 0xB7 and start is None:
            start = i
        elif xz[i] == 0xB7 and start is not None:
            if i - start >= 64:
                segs.append((start, xz[start:i]))
            start = None
    if start is not None:
        segs.append((start, xz[start:]))
    out.append(f"  非填充片段: {len(segs)}")
    for st, seg in segs[:3]:
        out.append(f"    @XOR+{st} len={len(seg)} 头={seg[:24].hex()} 头ascii={seg[:24]!r}")
    # 非b7数据是否可能是 BMP？
    for st, seg in segs[:3]:
        if seg.startswith(b"BM"):
            out.append(f"     → BMP 魔数! 偏移 {st} 全文件偏移 {len(d)-x+st}")

text = "\n".join(out)
with open("out_tmp31.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)