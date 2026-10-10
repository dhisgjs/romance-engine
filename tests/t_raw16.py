# -*- coding: utf-8 -*-
"""验证那 16 个恒定 raw 字节是否就是图片密钥/掩码。

对每个 V2 文件测试：
  1) raw16 直接作为 AES-ECB 密钥解 aes_zone
  2) xor_zone ^ raw16(循环)      -> 找图片魔数
  3) aes_zone ^ raw16(循环)      -> 找图片魔数
  4) raw16 十六进制字符串(32字符)作为密钥
  5) xor_zone 用 raw16 前2/4字节做 16/32 位滚动异或
"""
import os
from collections import Counter

from Crypto.Cipher import AES

V2 = b"\x07\x08V2\x08\x07"
XOR_KEY = 0x88
MAGICS = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG": "png",
    b"GIF8": "gif",
    b"BM": "bmp",
    b"RIFF": "riff",
    b"II*\x00": "tif",
    b"MM\x00*": "tif",
}


def fmt(b):
    for m, n in MAGICS.items():
        if b.startswith(m):
            return n
    if len(b) >= 12 and b[4:8] == b"ftyp":
        return "hevc"
    return None


def parse(d):
    if len(d) < 32 or d[:6] != V2:
        return None
    a = int.from_bytes(d[6:10], "little")
    x = int.from_bytes(d[10:14], "little")
    if a <= 0 or x < 0 or 15 + a + 16 > len(d):
        return None
    return a, x


def xor_rep(z, k):
    n = len(k)
    return bytes(b ^ k[i % n] for i, b in enumerate(z))


attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
res = Counter()
raws = Counter()
examples = []
n = 0
for r, _d, fl in os.walk(attach):
    for f in fl:
        if not f.endswith(".dat"):
            continue
        try:
            with open(os.path.join(r, f), "rb") as fh:
                d = fh.read()
        except OSError:
            continue
        p = parse(d)
        if not p:
            continue
        a, x = p
        aes_zone = d[15:15 + a]
        raw = d[15 + a:15 + a + 16]
        xor_zone = d[15 + a + 16:15 + a + 16 + x]
        raws[raw] += 1
        n += 1

        # 1) raw16 作为 ECB 密钥
        z = aes_zone[:len(aes_zone) - len(aes_zone) % 16]
        if z:
            pt = AES.new(raw, AES.MODE_ECB).decrypt(z)
            if fmt(pt):
                res["1_raw作ECB密钥"] += 1
                if len(examples) < 5:
                    examples.append(f"1 {f[:40]} {fmt(pt)}")

        # 2) xor_zone ^ raw16
        y = xor_rep(xor_zone, raw)
        if len(y) >= 8 and fmt(y):
            res["2_xor区^raw16"] += 1
            if len(examples) < 8:
                examples.append(f"2 {f[:40]} {fmt(y)} off0")

        # 3) aes_zone ^ raw16
        y = xor_rep(aes_zone, raw)
        if len(y) >= 8 and fmt(y):
            res["3_aes区^raw16"] += 1
            if len(examples) < 8:
                examples.append(f"3 {f[:40]} {fmt(y)}")

        # 5) 滑动 raw16 掩码（任意偏移）
        if x > 32 and not res["2_xor区^raw16"]:
            pass

    if n >= 500:
        break

lines = [f"扫描 {n} 个 V2 文件", "", "raw16 取值分布 (前5):"]
for k, v in raws.most_common(5):
    lines.append(f"  {k.hex()} x{v}")
lines.append("")
lines.append("命中统计:")
for k, v in res.most_common():
    lines.append(f"  {k}: {v}")
lines.append("")
lines.append("样例:")
lines.extend(examples)
if not examples:
    lines.append("  无")
text = "\n".join(lines)
with open("out_tmp34.txt", "w", encoding="utf-8") as fh:
    fh.write(text)
print(text)