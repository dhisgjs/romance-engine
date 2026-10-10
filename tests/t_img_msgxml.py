# -*- coding: utf-8 -*-
"""扫描所有 Msg_ 表中 type=3（图片）消息的 message_content，找 aeskey 属性。"""
import os
import sqlite3
from collections import Counter

root = os.path.join("data", "decrypted", "wxid_your_account_efcf", "message")
out = []
attrs = Counter()
samples = []
total_img = 0

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
                rows = c.execute(
                    f'SELECT local_type, message_content FROM "{t}" WHERE local_type IN (3,49) LIMIT 40').fetchall()
            except Exception:
                continue
            for lt, content in rows:
                if not content or "<img" not in str(content):
                    continue
                s = str(content)
                if "<img" in s:
                    total_img += 1
                if len(samples) < 12:
                    samples.append(s[:400])
                # 统计属性名
                import re
                for m in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', s):
                    attrs[m.group(1)] += 1
        c.close()
    except Exception as e:
        out.append(f"{fn}: {e}")

out.append(f"含 <img 的消息数: {total_img}")
out.append(f"\n出现的属性名统计 (前30):")
for k, v in attrs.most_common(30):
    out.append(f"   {k}: {v}")
out.append(f"\n样例 XML ({len(samples)}条):")
for s in samples:
    out.append(f"   {s}\n")

with open("out_tmp17.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"含<img消息: {total_img}")
print("属性统计:", attrs.most_common(20))