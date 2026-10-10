# -*- coding: utf-8 -*-
"""查 type49 消息各列实际内容。"""
import hashlib
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACC = "wxid_your_account_efcf"
mp = os.path.join("data", "decrypted", ACC, "message", "message_0.db")
t = "Msg_" + hashlib.md5(b"wxid_peer_example").hexdigest()[:32]
conn = sqlite3.connect(f"file:{mp}?mode=ro&immutable=1", uri=True)
conn.text_factory = lambda b: b.decode("utf-8", errors="replace")

cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{t}')")]
print("表列:", [c for c in cols if "content" in c or "msg" in c or "source" in c])

# 看一列有哪些可用的消息列
rows = conn.execute(f"SELECT {','.join([c for c in cols if 'content' in c or 'msg' in c or 'source' in c][:6])} FROM '{t}' WHERE local_type=49 LIMIT 3").fetchall()
for r in rows:
    for v in r:
        if v:
            s = v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
            print("  >", s[:120])
            print("  ---")
conn.close()