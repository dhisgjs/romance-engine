# -*- coding: utf-8 -*-
"""验证：emoticon.db 的 aes_key 能否解密 Persist 表情包文件（验证链路正确性）。"""
import os
import sqlite3

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

acc = "wxid_your_account_efcf"
root = os.path.join("data", "decrypted", acc)
base = rf"D:\personal\Documents\xwechat_files\{acc}"
out = []

# 取几个表情包 aes_key
p = os.path.join(root, "emoticon", "emoticon.db")
c = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
keys = list(c.execute("SELECT md5, aes_key FROM kNonStoreEmoticonTable WHERE aes_key IS NOT NULL AND aes_key != '' LIMIT 20"))
c.close()
out.append(f"表情包 aes_key 样本 {len(keys)} 条")

MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"wxgf", b"RIFF")
ok = 0
tested = 0
for md5, aes in keys:
    f = os.path.join(base, "business", "emoticon", "Persist", md5[:2].lower(), md5.lower())
    if not os.path.isfile(f):
        continue
    tested += 1
    with open(f, "rb") as fh:
        data = fh.read()
    if len(data) == 0 or len(data) % 16:
        continue
    # 尝试：hex32 → 16字节 AES key
    try:
        key = bytes.fromhex(aes[:32])
    except ValueError:
        # 或直接 ascii 32 → 取前16
        key = aes.encode("latin-1", errors="ignore")[:16]
    if len(key) != 16:
        continue
    dec = AES.new(key, AES.MODE_ECB).decrypt(data)
    try:
        dec = unpad(dec, 16)
    except Exception:
        pass
    fmt = "?"
    for m in MAGICS:
        if dec.startswith(m):
            fmt = m[:3]
    if fmt != "?":
        ok += 1
        if ok <= 3:
            out.append(f"  {md5[:12]} key={aes[:32]} -> 格式={fmt} 头={dec[:12].hex()}")

out.append(f"\n测试 {tested} 个表情包，成功解密 {ok} 个")
out.append("结论: " + ("aes_key 形态正确 ✓" if ok > 0 else "aes_key 形态错误 ✗"))

with open("out_tmp14.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out))