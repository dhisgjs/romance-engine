# -*- coding: utf-8 -*-
"""看表的所有列 + 107 行的 compress_content 原始内容。"""
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
print("全部列:", cols)

row = conn.execute(f"SELECT message_content, WCDB_CT_message_content, compress_content FROM '{t}' WHERE local_id=107").fetchone()
mc, ctmc, comp = row
print("\nmessage_content head:", mc[:16].hex() if mc else "空")
print("WCDB_CT_message_content:", ctmc)
if comp:
    print("compress_content head:", comp[:16].hex() if isinstance(comp, bytes) else repr(comp)[:60])
    if isinstance(comp, bytes):
        try:
            print("  as utf8:", comp[:80].decode("utf-8", "replace"))
        except Exception:
            pass
else:
    print("compress_content: 空")
conn.close()