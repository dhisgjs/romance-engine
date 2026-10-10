# -*- coding: utf-8 -*-
"""验证微信4.x V2图片密钥 = 文件名MD5的假设（还有各种常见候选）。"""
import os
from Crypto.Cipher import AES

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"
MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")


def is_img(d: bytes) -> bool:
    return any(d.startswith(m) for m in MAGICS) or (d[:4] == b"RIFF" and d[8:12] == b"WEBP")


def try_key(name_md5: str, ciphertext: bytes) -> bool:
    for kb in (name_md5.encode(), bytes.fromhex(name_md5[:32]), name_md5[:16].encode()):
        if len(kb) != 16:
            continue
        try:
            dec = AES.new(kb, AES.MODE_ECB).decrypt(ciphertext)
        except Exception:
            continue
        if is_img(dec):
            return True
    return False


# 取 50 个不同的原图文件，测试 文件名MD5 假设
files = []
seen = set()
for root, _d, fl in os.walk(attach):
    for f in fl:
        if not f.endswith(".dat") or f.endswith(("_t.dat", "_h.dat")):
            continue
        p = os.path.join(root, f)
        base = f[:-4]  # 去掉 .dat
        if base in seen or len(base) != 32:
            continue
        seen.add(base)
        files.append((base, p))
        if len(files) >= 50:
            break
    if len(files) >= 50:
        break

hit_name_md5 = 0
hit_bytes = 0
rows = []
for base, p in files:
    with open(p, "rb") as fh:
        d = fh.read(31)
    if d[:6] != V2:
        continue
    ct = d[15:31]
    ok1 = try_key(base, ct)
    ok2 = try_key(bytes.fromhex(base)[:16].hex(), ct)  # 16字节二进制hex串
    ok3 = try_key("cfcd208495d565ef", ct)  # 经典V1 key
    rows.append((base, ok1, ok2, ok3))
    if ok1:
        hit_name_md5 += 1
    if ok2:
        hit_bytes += 1

with open("out_tmp4.txt", "w", encoding="utf-8") as out:
    out.write(f"测试 {len(rows)} 个原图文件:\n")
    out.write(f"  文件名32hex作为key: {hit_name_md5} 命中\n")
    out.write(f"  文件名16字节hex串: {hit_bytes} 命中\n")
    for base, ok1, ok2, ok3 in rows[:30]:
        out.write(f"  {base}: name_md5={ok1} hexbytes={ok2}\n")