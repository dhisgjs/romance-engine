# -*- coding: utf-8 -*-
"""在消息库的图片消息 content 中找 aeskey / md5 属性。"""
import os
import re
import sqlite3

root = os.path.join("data", "decrypted", "wxid_your_account_efcf")
out = []

# 找到消息库
msg_db = None
for dirpath, _dirs, files in os.walk(root):
    for fn in files:
        if fn.startswith("message") and fn.endswith(".db"):
            msg_db = os.path.join(dirpath, fn)
            break
    if msg_db:
        break
out.append(f"消息库: {msg_db}")

if msg_db:
    c = sqlite3.connect(f"file:{msg_db}?mode=ro&immutable=1", uri=True)
    # 找 type=3 (图片) 的消息 content 样例
    try:
        rows = list(c.execute(
            "SELECT rowid, content FROM message WHERE type=3 AND content IS NOT NULL LIMIT 8"))
    except Exception as e:
        out.append(f"查询失败: {e}")
        rows = []
    c.close()
    out.append(f"图片消息: {len(rows)}")
    for rid, content in rows:
        out.append(f"  rowid={rid}: {str(content)[:300]}")

with open("out_tmp15.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out))