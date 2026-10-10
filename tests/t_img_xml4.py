# -*- coding: utf-8 -*-
"""提取图片消息 XML（修正列名）。"""
import os
import re
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress

root = "data/decrypted/wxid_your_account_efcf/message"
types = Counter()
attrs = Counter()
img_samples = []
total = 0

for fn in sorted(os.listdir(root)):
    if not fn.endswith(".db"):
        continue
    p = os.path.join(root, fn).replace("\\", "/")
    c = sqlite3.connect("file:" + p + "?mode=ro&immutable=1", uri=True)
    c.text_factory = lambda b: b.decode("utf-8", errors="replace")
    tabs = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
    for t in tabs:
        # 先看列
        cols = [r[1] for r in c.execute('PRAGMA table_info("' + t + '")')]
        sel = ["local_type", "message_content", "compress_content"]
        sel = [x for x in sel if x in cols]
        ctm = "WCDB_CT_message_content" if "WCDB_CT_message_content" in cols else None
        if ctm:
            sel.append(ctm)
        try:
            rows = c.execute("SELECT " + ", ".join(sel) + ' FROM "' + t + '"').fetchall()
        except Exception:
            continue
        for row in rows:
            lt = row[0]
            mc = row[1] if len(row) > 1 else None
            cc = row[2] if len(row) > 2 else None
            ct = row[3] if len(row) > 3 else None
            types[lt] += 1
            total += 1
            try:
                content = wcdb_decompress(mc or cc, ct)
            except Exception:
                continue
            if content and "<img" in content:
                for m in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', content):
                    attrs[m.group(1)] += 1
                if len(img_samples) < 15:
                    img_samples.append(content[:500])
    c.close()

out = [f"消息总数: {total}", "", "local_type 分布:"]
for lt, n in types.most_common(20):
    out.append(f"  type {lt}: {n}")
out.append("\n图片消息 XML 属性统计:")
for k, v in attrs.most_common(40):
    out.append(f"  {k}: {v}")
out.append(f"\n图片 XML 样例 ({len(img_samples)}):")
for s in img_samples:
    out.append("  " + s + "\n")
with open("out_tmp22.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"总 {total}")
print("类型:", types.most_common(15))
print("图片属性:", attrs.most_common(20))