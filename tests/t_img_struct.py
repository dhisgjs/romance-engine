# -*- coding: utf-8 -*-
"""分析 V2 文件结构：aes_size/xor_size 分布 + XOR 尾部能否解出合法数据。"""
import os
from collections import Counter

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"
MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")


def is_img(d: bytes) -> bool:
    return any(d.startswith(m) for m in MAGICS) or (d[:4] == b"RIFF" and d[8:12] == b"WEBP")


aes_sizes, xor_sizes = Counter(), Counter()
pairs = Counter()
paths = []
for root, _d, files in os.walk(attach):
    for f in files:
        if not f.endswith(".dat"):
            continue
        p = os.path.join(root, f)
        try:
            with open(p, "rb") as fh:
                h = fh.read(15)
            if h[:6] != V2:
                continue
            a = int.from_bytes(h[6:10], "little")
            x = int.from_bytes(h[10:14], "little")
        except OSError:
            continue
        aes_sizes[a] += 1
        xor_sizes[x] += 1
        pairs[(a, x)] += 1
        paths.append((os.path.getsize(p), p))

with open("out_tmp3.txt", "w", encoding="utf-8") as out:
    out.write(f"aes_size 分布: {aes_sizes.most_common(10)}\n")
    out.write(f"xor_size 分布: {xor_sizes.most_common(10)}\n")
    out.write(f"(aes,xor) 组合: {pairs.most_common(10)}\n\n")

    # 取最大的 3 个文件，看 XOR 尾部解出来是什么
    paths.sort(reverse=True)
    for sz, p in paths[:3]:
        with open(p, "rb") as fh:
            data = fh.read()
        x = int.from_bytes(data[10:14], "little")
        a = int.from_bytes(data[6:10], "little")
        tail = bytes(b ^ 0x88 for b in data[-x:]) if x <= len(data) else b""
        out.write(f"{os.path.basename(p)} size={sz} aes={a} xor={x}\n")
        out.write(f"   XOR尾部前32字节hex: {tail[:32].hex()}\n")
        out.write(f"   XOR尾部可读: {tail[:64]!r}\n")
        # 尾部是否是 JPEG 结束标记 FFD9 或 PNG IEND
        out.write(f"   尾部含 FFD9: {b'\\xff\\xd9' in tail}  含 IEND: {b'IEND' in tail}\n")
        # 猜测：XOR 尾部可能压缩了图片主体（zlib/gzip）
        import zlib
        for wbits, name in ((15, "zlib"), (47, "auto-gzip"), (-15, "raw-deflate")):
            try:
                dec = zlib.decompress(tail, wbits)
                out.write(f"   {name} 解压成功: {len(dec)} 字节, 头={dec[:16].hex()} is_img={is_img(dec)}\n")
                break
            except Exception as e:
                out.write(f"   {name} 失败: {type(e).__name__}\n")