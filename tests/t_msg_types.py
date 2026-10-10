# -*- coding: utf-8 -*-
"""看消息库 local_type 分布 + 真实 XML 内容。"""
import os
import re
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress

root = os.path.join("data", "decrypted", "wxid_your_account_efcf", "message")
types = Counter()
samples = {}
total = 0

for fn in sorted(os.listdir(root)):
    if not fn.endswith(".db"):
        continue
    p = os.path.join(root, fn)
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
        c.text_factory = lambda b: b.decode("utf-8", errors="replace")
        tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
        for t in tabs[:60]:
            try:
                rows = c.execute(
                    f'SELECT local_type, message_content, compress_content, WCDB_CT_message_content, WCDB_CT_compress_content FROM "{t}" LIMIT 200').fetchall()
            except Exception:
                continue
            for lt, mc, cc, ctm, ctc in rows:
                types[lt] += 1
                total += 1
                if lt not in samples and len(samples) < 8:
                    samples[lt] = (wcdb_decompress(mc or cc, ctm or ctc) or "")[:220]
        c.close()
    except Exception as e:
        print(f"{fn}: {e}")

out = [f"消息总数: {total}", "local_type 分布 (top 15):"]
for lt, n in types.most_common(15):
    out.append(f"  type {lt}: {n}")
out.append("各类型样例:")
for lt, s in samples.items():
    out.append(f"--- type {lt}: {s!r}")
with open("out_tmp19.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out))