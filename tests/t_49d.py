# -*- coding: utf-8 -*-
"""debug：_convert 内部 content 到底取了什么。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import Store

# 手动构造 rec，模拟 _convert 的输入
import hashlib, sqlite3, zstandard
ACC = "wxid_your_account_efcf"
mp = os.path.join("data", "decrypted", ACC, "message", "message_0.db")
t = "Msg_" + hashlib.md5(b"wxid_peer_example").hexdigest()[:32]
conn = sqlite3.connect(f"file:{mp}?mode=ro&immutable=1", uri=True)
conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{t}')")]
# 和 messages() 一样的 select
select = ["local_type", "create_time", "real_sender_id"]
for _c in ("message_content", "compress_content"):
    if _c in cols:
        select.append(_c)
        if f"WCDB_CT_{_c}" in cols:
            select.append(f"WCDB_CT_{_c}")
for _s in ("source", "origin_source"):
    if _s in cols:
        select.append(_s)
        if f"WCDB_CT_{_s}" in cols:
            select.append(f"WCDB_CT_{_s}")
select.append("local_id")
rows = conn.execute(f"SELECT {','.join(select)} FROM '{t}' WHERE local_type=49 LIMIT 1").fetchall()
keys = [k.split(' AS ')[-1] for k in select]
rec = dict(zip(keys, rows[0]))
print("rec keys:", list(rec.keys()))
print("message_content:", repr(rec.get("message_content"))[:60] if rec.get("message_content") else "空")
print("compress_content:", repr(rec.get("compress_content"))[:60] if rec.get("compress_content") else "空")
print("WCDB_CT_compress_content:", rec.get("WCDB_CT_compress_content"))
conn.close()

# 手动走 _convert
s = Store(os.path.join("data", "decrypted"), ACC)
m = s._convert(rec, {}, "wxid_peer_example", "wxid_your_account")
print("\n_convert 后 text:", repr(m["text"]))