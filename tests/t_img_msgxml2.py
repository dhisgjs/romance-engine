# -*- coding: utf-8 -*-
"""从消息库提取 type=3 图片消息（解压 message_content/compress_content），找 aeskey。"""
import os
import re
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress

root = os.path.join("data", "decrypted", "wxid_your_account_efcf", "message")
out = []
attrs = Counter()
samples = []
total_img = 0
img_msgs = []

for fn in sorted(os.listdir(root)):
    if not fn.endswith(".db"):
        continue
    p = os.path.join(root, fn)
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
        c.text_factory = lambda b: b.decode("utf-8", errors="replace")
        tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
        for t in tabs:
            try:
                cols = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]
                q = f'SELECT local_type, message_content, compress_content, WCDB_CT_message_content, WCDB_CT_compress_content FROM "{t}" WHERE local_type=3 LIMIT 30'
                rows = c.execute(q).fetchall()
            except Exception:
                continue
            for lt, mc, cc, ctm, ctc in rows:
                content = wcdb_decompress(mc or cc, ctm or ctc)
                if not content or "<img" not in content:
                    continue
                total_img += 1
                if len(samples) < 15:
                    samples.append(content[:450])
                for m in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', content):
                    attrs[m.group(1)] += 1
                img_msgs.append(content)
        c.close()
    except Exception as e:
        out.append(f"{fn}: {e}")

out.append(f"图片消息总数(解压后含<img): {total_img}")
out.append(f"\n属性统计 (前40):")
for k, v in attrs.most_common(40):
    out.append(f"   {k}: {v}")
out.append(f"\n样例 XML ({len(samples)}):")
for s in samples:
    out.append(f"   {s[:400]}\n")

with open("out_tmp18.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"图片消息: {total_img}")
print("属性:", attrs.most_common(20))