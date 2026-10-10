# -*- coding: utf-8 -*-
"""统计 cache 下明文图片（Thumb/*.jpg 等），看能覆盖多少条图片消息。

Thumb 文件名格式: <local_id>_<timestamp>_thumb.jpg
Bubble 文件名: <md5>_b.dat，可能是加密的表情/气泡图。
"""
import os
import re
from collections import Counter

acct = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
cache = os.path.join(acct, "cache")

MAGICS = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"GIF8": "gif",
          b"BM": "bmp", b"RIFF": "webp", b"wXgf": "hevc", b"II*\x00": "tif"}


def ftype(head):
    for m, n in MAGICS.items():
        if head.startswith(m):
            return n
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "mp4/heic"
    return None


lines = []
plain = Counter()
plain_files = []
bubble = []
other = Counter()

for r, _d, fl in os.walk(cache):
    for f in fl:
        p = os.path.join(r, f)
        try:
            with open(p, "rb") as fh:
                head = fh.read(16)
        except OSError:
            continue
        t = ftype(head)
        rel = os.path.relpath(p, cache)
        if t:
            plain[t] += 1
            plain_files.append((os.path.getsize(p), rel, t))
        elif "_b.dat" in f:
            bubble.append((os.path.getsize(p), rel, head[:8].hex()))
        else:
            other[rel.split("\\")[0].split("/")[0]] += 1

lines.append("=== cache 明文图片统计 ===")
for k, v in plain.most_common():
    lines.append(f"  {k}: {v} 个")
lines.append("")
lines.append("明文图片清单 (前40):")
for sz, rel, t in sorted(plain_files, key=lambda x: -x[0])[:40]:
    lines.append(f"  {sz:>9} {t:5} {rel}")
lines.append("")
lines.append(f"=== Bubble _b.dat: {len(bubble)} 个 ===")
for sz, rel, h in bubble[:15]:
    lines.append(f"  {sz:>9} {rel} head={h}")
lines.append("")
lines.append("=== 非明文按类目 ===")
for k, v in other.most_common():
    lines.append(f"  {k}: {v}")

# 抽一个 thumb jpg 验证完整可解码
lines.append("")
lines.append("=== Thumb jpg 完整性抽样 ===")
ok = bad = 0
for sz, rel, t in plain_files:
    if "Thumb" not in rel:
        continue
    p = os.path.join(cache, rel)
    try:
        with open(p, "rb") as fh:
            d = fh.read()
    except OSError:
        continue
    if d[:2] == b"\xff\xd8" and d[-2:] == b"\xff\xd9":
        ok += 1
    else:
        bad += 1
lines.append(f"  头尾完整: {ok}, 不完整: {bad}")

text = "\n".join(lines)
with open("out_tmp37.txt", "w", encoding="utf-8") as fh:
    fh.write(text)
print(text)