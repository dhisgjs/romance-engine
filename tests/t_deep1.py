# -*- coding: utf-8 -*-
"""深挖一个样本：文件找到了但 aeskey 解不出。试所有 key 变体 + 全文件逐块解密。"""
import os
import re
import sqlite3
import sys
import base64

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress
from backend.core.media import detect_format, decrypt_v2_bytes

root = "data/decrypted/wxid_your_account_efcf"
acc = "wxid_your_account_efcf"
src = rf"D:\personal\Documents\xwechat_files\{acc}"
attach = os.path.join(src, "msg", "attach")

disk = {}
for r, _d, files in os.walk(attach):
    for f in files:
        if f.endswith(".dat"):
            base = re.sub(r"_([th])\.dat$", "", f)
            disk.setdefault(base[:-4].lower(), []).append(os.path.join(r, f))

# 找第一个能找到文件的 (md5,aeskey)
pair = None
msg_dir = os.path.join(root, "message")
for fn in sorted(os.listdir(msg_dir)):
    if not fn.endswith(".db"):
        continue
    p = os.path.join(msg_dir, fn).replace("\\", "/")
    cc = sqlite3.connect("file:" + p + "?mode=ro&immutable=1", uri=True)
    cc.text_factory = lambda b: b.decode("utf-8", errors="replace")
    for (t,) in cc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"):
        cols = [r[1] for r in cc.execute('PRAGMA table_info("' + t + '")')]
        if "message_content" not in cols:
            continue
        for mc, ccx, ct in cc.execute(
                'SELECT message_content, compress_content, WCDB_CT_message_content FROM "' + t + '" LIMIT 100'):
            try:
                content = wcdb_decompress(mc or ccx, ct)
            except Exception:
                continue
            if content and '<img' in content:
                m = re.search(r'md5="([0-9a-fA-F]{32})"', content)
                k = re.search(r'aeskey="([0-9a-fA-F]{32})"', content)
                if m and k and disk.get(m.group(1).lower()):
                    pair = (m.group(1).lower(), k.group(1).lower())
                    break
        if pair:
            break
    cc.close()
    if pair:
        break

if not pair:
    print("没找到可测样本")
    sys.exit(0)

md5, aeshex = pair
pth = disk[md5][0]
print(f"md5={md5}")
print(f"aeskey={aeshex}")
print(f"file={os.path.basename(pth)} path={pth}")
with open(pth, "rb") as fh:
    data = fh.read()
print(f"filesize={len(data)} head={data[:15].hex()}")
a = int.from_bytes(data[6:10], "little")
x = int.from_bytes(data[10:14], "little")
print(f"aes_size={a} xor_size={x} raw_zone_len={len(data)-15-((a+15)//16*16)-x}")

# key 变体
variants = {
    "hex解码(16B)": bytes.fromhex(aeshex),
    "hex解码(32B)": bytes.fromhex(aeshex) * 2,  # 32 字节（AES-256?）
    "前16字符": aeshex[:16].encode("latin-1"),
    "后16字符": aeshex[16:].encode("latin-1"),
    "原32字符": aeshex.encode("latin-1"),
    "base64": base64.b64decode(aeshex + "==")[:16] if len(aeshex) % 4 else base64.b64decode(aeshex),
}
print("\n--- 各 key 变体尝试 decrypt_v2_bytes ---")
for name, key in variants.items():
    r = decrypt_v2_bytes(data, key)
    print(f"  {name}: len={len(key)} -> {'成功 ' + r[1] if r else '失败'}")

# 全文件逐块：用 hex 解码 key 解每个16B块，找魔数
key = bytes.fromhex(aeshex)
cipher = __import__("Crypto.Cipher.AES", fromlist=["AES"]).AES.new(key, __import__("Crypto.Cipher.AES", fromlist=["AES"]).AES.MODE_ECB)
hits = []
for off in range(0, len(data) - 15, 16):
    dec = cipher.decrypt(data[off:off + 16])
    if detect_format(dec) != "bin":
        hits.append((off, dec.hex()))
        if len(hits) > 5:
            break
print(f"\n--- hex解码key 逐块解密魔数命中: {len(hits)} ---")
for off, h in hits:
    print(f"  @{off}: {h}")

# 若 head15 不是 V2 但文件是 V2？重读确认
if data[:6] != b"\x07\x08V2\x08\x07":
    print("警告: 非V2格式!")
else:
    # 也看 XOR 区是否有直接 BM
    tail = data[-x:] if x > 0 else b""
    i_bm = tail.find(b"BM")
    print(f"\nXOR区({len(tail)}) 内 find BM: {i_bm}")
    print(f"XOR区前16: {tail[:16].hex()} {tail[:16]!r}")