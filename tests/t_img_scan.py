# -*- coding: utf-8 -*-
import os
attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
lines = []
n = total = v2 = v1 = other = 0
for root, _d, files in os.walk(attach):
    for f in files:
        if not f.endswith(".dat"):
            continue
        total += 1
        p = os.path.join(root, f)
        try:
            with open(p, "rb") as fh:
                h = fh.read(16)
        except OSError:
            continue
        magic = h[:6]
        if magic == b"\x07\x08V2\x08\x07":
            v2 += 1
        elif magic == b"\x07\x08V1\x08\x07":
            v1 += 1
        else:
            other += 1
        if n < 15:
            n += 1
            lines.append(f"{f[:80]:82s} magic={magic.hex()} size={os.path.getsize(p)}")

bigs = []
for root, _d, files in os.walk(attach):
    for f in files:
        if f.endswith(".dat"):
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fh:
                    head = fh.read(6)
                if head == b"\x07\x08V2\x08\x07":
                    bigs.append((os.path.getsize(p), p))
            except OSError:
                pass
bigs.sort(reverse=True)

with open("out_tmp2.txt", "w", encoding="utf-8") as out:
    out.write(f"total={total} V2={v2} V1={v1} other={other}\n")
    out.write("\n".join(lines))
    out.write("\n\n最大5个V2:\n")
    for sz, p in bigs[:5]:
        with open(p, "rb") as fh:
            d = fh.read(200)
        out.write(
            f"{os.path.basename(p)} size={sz} "
            f"head16_ct={d[15:31].hex()} aes_size={int.from_bytes(d[6:10],'little')} "
            f"xor_size={int.from_bytes(d[10:14],'little')}\n"
        )