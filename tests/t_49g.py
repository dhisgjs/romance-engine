# -*- coding: utf-8 -*-
"""用 messages() 拿到的 49 消息 mid → 反查原始行。"""
import hashlib
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import Store

ACC = "wxid_your_account_efcf"
s = Store(os.path.join("data", "decrypted"), ACC)
n49 = [m for m in s.messages("wxid_peer_example") if m["type"] == 49]
print("49 消息:", len(n49), "| 第一条 mid:", n49[0]["mid"])

mp = os.path.join("data", "decrypted", ACC, "message", "message_0.db")
t = "Msg_" + hashlib.md5(b"wxid_peer_example").hexdigest()[:32]
conn = sqlite3.connect(f"file:{mp}?mode=ro&immutable=1", uri=True)
conn.text_factory = lambda b: b.decode("utf-8", errors="replace")

for m in n49[:3]:
    lid = m["mid"].split("|")[-1]
    row = conn.execute(
        f"SELECT local_type, message_content, WCDB_CT_message_content, compress_content, "
        f"source, WCDB_CT_source, origin_source FROM '{t}' WHERE local_id=?", (lid,)).fetchone()
    if row:
        lt, mc, ct, comp, src, st, orig = row
        print(f"\nlid={lid} type_raw={lt} (低32={lt & 0xFFFFFFFF})")
        print(f"  message_content: {repr(mc)[:60] if mc else '空'}")
        print(f"  compress_content: {repr(comp)[:100] if comp else '空'}")
        print(f"  source: {repr(src)[:60] if src else '空'}")
        print(f"  origin_source: {repr(orig)[:60] if orig else '空'}")
conn.close()