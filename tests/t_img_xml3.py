# -*- coding: utf-8 -*-
"""正确提取图片消息 XML（避开 shell 引号问题，用脚本文件）。"""
import os
import re
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress

root = os.path.join("data", "decrypted", "wxid_your_account_efcf", "message")
types = Counter()
attrs = Counter()
img_samples = []
total = 0

for fn in sorted(os.listdir(root)):
    if not fn.endswith(".db"):
        continue
    p = os.path.join(root, fn).replace("\\", "/")
    try:
        c = sqlite3.connect("file:" + p + "?mode=ro&immutable=1", uri=True)
        c.text_factory = lambda b: b.decode("utf-8", errors="replace")
        tabs = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
        for t in tabs:
            try:
                cnt = c.execute('SELECT count(*) FROM "' + t + '"').fetchone()[0]
            except Exception:
                continue
            if not cnt:
                continue
            try:
                rows = c.execute(
                    'SELECT local_type, message_content, compress_content,'
                    ' WCDB_CT_message_content, WCDB_CT_compress_content FROM "' + t + '"'
                ).fetchall()
            except Exception:
                continue
            for lt, mc, cc, ctm, ctc in rows:
                types[lt] += 1
                total += 1
                content = wcdb_decompress(mc or cc, ctm or ctc)
                if content and "<img" in content:
                    for m in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', content):
                        attrs[m.group(1)] += 1
                    if len(img_samples) < 15:
                        img_samples.append(content[:500])
        c.close()
    except Exception as e:
        print(f"{fn}: {e}")

out = [f"消息总数: {total}", "", "local_type 分布:"]
for lt, n in types.most_common(20):
    out.append(f"  type {lt}: {n}")
out.append("")
out.append("图片消息 XML 属性统计:")
for k, v in attrs.most_common(40):
    out.append(f"  {k}: {v}")
out.append("")
out.append(f"图片 XML 样例 ({len(img_samples)}):")
for s in img_samples:
    out.append("  " + s + "\n")

with open("out_tmp21.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"总消息 {total}, 图片消息 {sum(v for k, v in attrs.items())}")
print("类型分布:", types.most_common(15))
print("图片属性:", attrs.most_common(15))