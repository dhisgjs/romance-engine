# -*- coding: utf-8 -*-
"""按 aes/xor 比例找小图（图片主体在AES区），完整分析。"""
import os

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"

rows = []
for root, _d, fl in os.walk(attach):
    for f in fl:
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
            sz = os.path.getsize(p)
        except OSError:
            continue
        # aes 小、xor 小 的 = 小图
        if a <= 1024 and x <= 2000:
            rows.append((sz, a, x, p, f))

rows.sort()
out = []
out.append(f"小图候选( aes<=1024, xor<=2000 ): {len(rows)}")
for sz, a, x, p, f in rows[:10]:
    out.append(f"  {f[:50]:52s} size={sz} aes={a} xor={x}")
    with open(p, "rb") as fh:
        d = fh.read()
    aes_end = 15 + ((a + 15) // 16 * 16)
    raw = d[aes_end:len(d) - x]
    xz = bytes(b ^ 0x88 for b in d[len(d) - x:])
    out.append(f"     raw区({len(raw)}): {raw[:24].hex()}")
    out.append(f"     xor区解后前24: {xz[:24].hex()} 可读={xz[:32]!r}")

with open("out_tmp8.txt", "w", encoding="utf-8") as fh_:
    fh_.write("\n".join(out))