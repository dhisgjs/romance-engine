# -*- coding: utf-8 -*-
"""用复合 local_type 查 49 消息，看 content 列分布。"""
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

# 找 3 条（last 复合值 & 0xFFFFFFFF == 49）
rows = conn.execute(
    f"SELECT local_type, message_content, WCDB_CT_message_content, compress_content, "
    f"source, WCDB_CT_source, origin_source, local_id "
    f"FROM '{t}' WHERE (local_id % 2 = 0) LIMIT 50").fetchall()
c49 = [r for r in rows if (r[0] & 0xFFFFFFFF) == 49]
print(f"复合49消息: {len(c49)} 条")
for r in c49[:5]:
    lt, mc, cc_t, comp, src, src_t, origin, lid = r
    print(f"  local_id={lid} type_raw={lt}")
    print(f"    message_content: {repr(mc)[:80] if mc else '空'}")
    print(f"    compress_content: {repr(comp)[:80] if comp else '空'}")
    print(f"    source: {repr(src)[:60] if src else '空'}")
    print(f"    origin_source: {repr(origin)[:60] if origin else '空'}")
conn.close()