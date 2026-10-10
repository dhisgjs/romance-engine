# -*- coding: utf-8 -*-
"""排查：哪些消息类型显示了"代码"（原始 XML/JSON/长内容）。"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import Store

ACC = "wxid_your_account_efcf"
store = Store(os.path.join("data", "decrypted"), ACC)

# 找一个消息多的聊天
known = store.known_talkers()
t = "wxid_peer_example" if "wxid_peer_example" in known else next(iter(known))
msgs = store.messages(t)
print(f"聊天 {t} 共 {len(msgs)} 条")

# 统计各类型 + 内容是否像"代码"
type_stats = {}
code_like = []
for m in msgs:
    tt = m["type"]
    type_stats[tt] = type_stats.get(tt, 0) + 1
    txt = m.get("text") or ""
    # 判断"代码样"：含大量标签/大括号/非常规文本
    if (("<" in txt and ">" in txt) or "{" in txt and "}" in txt
            or txt.count("\n") > 5 or len(txt) > 500):
        code_like.append((tt, txt[:60].replace("\n", " ")))

print("类型分布:", dict(sorted(type_stats.items(), key=lambda x: -x[1])))
print(f"\n'代码样'消息 {len(code_like)} 条，类型分布:")
from collections import Counter
c = Counter(x[0] for x in code_like)
for tt, n in c.most_common():
    print(f"  类型{tt}: {n} 条")
    for t2, s in code_like:
        if t2 == tt:
            print(f"    例: {s}")
            break

# 看几种具体类型的内容样本（判断哪些该特殊处理）
for tt in [x for x, _ in c.most_common()][:6]:
    sample = next((m for m in msgs if m["type"] == tt and m.get("text")), None)
    if sample:
        print(f"\n--- 类型{tt} 完整内容 ---")
        print(sample["text"][:300])