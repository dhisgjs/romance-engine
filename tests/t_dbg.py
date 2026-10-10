# -*- coding: utf-8 -*-
"""直接读单个 Msg 表，定位为何 0 行。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress

p = "data/decrypted/wxid_your_account_efcf/message/message_0.db"
import sqlite3

c = sqlite3.connect("file:" + p + "?mode=ro&immutable=1", uri=True)
c.text_factory = lambda b: b.decode("utf-8", errors="replace")
t = "Msg_8b5922e925a331d21f74cdc49daecc9f"
print("count:", c.execute('SELECT count(*) FROM "' + t + '"').fetchone()[0])
rows = c.execute(
    'SELECT local_type, message_content, compress_content,'
    ' WCDB_CT_message_content, WCDB_CT_compress_content FROM "' + t + '" LIMIT 20').fetchall()
print("fetched rows:", len(rows))
for r in rows[:10]:
    lt, mc, cc, ctm, ctc = r
    try:
        d = wcdb_decompress(mc or cc, ctm or ctc)
        print(f"  type={lt} raw={repr((mc or cc))[:60]} -> {repr(d)[:150]}")
    except Exception as e:
        print(f"  type={lt} 异常: {type(e).__name__}: {e}  raw={repr((mc or cc))[:80]}")