# -*- coding: utf-8 -*-
"""验证：消息 XML 的 aeskey（hex编码的32位ASCII）能否解密对应图片 .dat。"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress
from backend.core.media import MediaStore, detect_format

root = "data/decrypted/wxid_your_account_efcf"
acc = "wxid_your_account_efcf"
src = rf"D:\personal\Documents\xwechat_files\{acc}"
store = MediaStore(acc, root, os.path.join("data", "keys"), src)

# 收集 (md5, aeskey) 对
pairs = []
msg_dir = os.path.join(root, "message")
for fn in sorted(os.listdir(msg_dir)):
    if not fn.endswith(".db"):
        continue
    p = os.path.join(msg_dir, fn).replace("\\", "/")
    c = sqlite3.connect("file:" + p + "?mode=ro&immutable=1", uri=True)
    c.text_factory = lambda b: b.decode("utf-8", errors="replace")
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"):
        cols = [r[1] for r in c.execute('PRAGMA table_info("' + t + '")')]
        if "message_content" not in cols:
            continue
        try:
            rows = c.execute('SELECT message_content, compress_content, WCDB_CT_message_content FROM "' + t + '"').fetchall()
        except Exception:
            continue
        for mc, cc, ct in rows:
            try:
                content = wcdb_decompress(mc or cc, ct)
            except Exception:
                continue
            if content and "<img" in content:
                m = re.search(r'md5="([0-9a-fA-F]{32})"', content)
                k = re.search(r'aeskey="([0-9a-fA-F]{32})"', content)
                if m and k:
                    pairs.append((m.group(1).lower(), k.group(1).lower()))
    c.close()

print(f"找到 (md5, aeskey) 对: {len(pairs)}")

ok = fail = 0
details = []
for md5, aeshex in pairs:
    for variant in ("t", "full"):
        srcpath = store.resolve_image(md5, variant)
        if not srcpath:
            continue
        try:
            with open(srcpath, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        # key = hex解码的16字节
        try:
            key = bytes.fromhex(aeshex)
        except ValueError:
            continue
        if len(key) != 16:
            continue
        from backend.core.media import decrypt_v2_bytes
        r = decrypt_v2_bytes(data, key)
        if r:
            ok += 1
            if len(details) < 8:
                details.append(f"  ✓ {md5[:12]} variant={variant} aeskey={aeshex}({bytes.fromhex(aeshex)!r}) -> {r[1]} {len(r[0])}B")
            break
        else:
            fail += 1
            if len(details) < 20 and fail <= 12:
                details.append(f"  ✗ {md5[:12]} variant={variant} aeskey={aeshex} 解密失败")
            break

print(f"成功 {ok} / 失败 {fail}")
print("\n".join(details))
with open("out_tmp23.txt", "w", encoding="utf-8") as f:
    f.write(f"pairs={len(pairs)} ok={ok} fail={fail}\n" + "\n".join(details))