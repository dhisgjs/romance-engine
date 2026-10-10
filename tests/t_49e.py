# -*- coding: utf-8 -*-
"""debug：追一条 49 消息从数据库行到 text 的完整路径。"""
import hashlib
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import Store, extract_appmsg_title, wcdb_decompress

ACC = "wxid_your_account_efcf"
s = Store(os.path.join("data", "decrypted"), ACC)
n49 = [m for m in s.messages("wxid_peer_example") if m["type"] == 49]

# 直接复现 messages() 的读取，逐列看
mp = os.path.join("data", "decrypted", ACC, "message", "message_0.db")
t = "Msg_" + hashlib.md5(b"wxid_peer_example").hexdigest()[:32]
conn = sqlite3.connect(f"file:{mp}?mode=ro&immutable=1", uri=True)
conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
cols = [r[1] for r in conn.execute(f"PRAGMA table_info('{t}')")]
sel = ["local_type", "create_time", "real_sender_id"]
for _c in ("message_content", "compress_content", "source", "origin_source"):
    if _c in cols:
        sel.append(_c)
        if f"WCDB_CT_{_c}" in cols:
            sel.append(f"WCDB_CT_{_c}")
sel.append("local_id")
print("select:", sel)
row = conn.execute(f"SELECT {','.join(sel)} FROM '{t}' WHERE local_type=49 LIMIT 1").fetchone()
if row:
    rec = dict(zip([k.split(' AS ')[-1] for k in sel], row))
    for k, v in rec.items():
        if v:
            if isinstance(v, bytes):
                print(f"  {k}: {v[:60]!r}")
            else:
                print(f"  {k}: {v}")
    # 手动解压看
    content = wcdb_decompress(rec.get("message_content") or rec.get("compress_content"),
                              rec.get("WCDB_CT_message_content") or rec.get("WCDB_CT_compress_content"))
    print("\n解压后 content:", repr(content)[:120])
    print("extract_title:", extract_appmsg_title(content))
conn.close()