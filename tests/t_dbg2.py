# -*- coding: utf-8 -*-
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core import media as m  # noqa: E402
from backend.core.models import wcdb_decompress  # noqa: E402

ACCT = "wxid_your_account_efcf"
SRC = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
DEC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "decrypted"))
st = m.MediaStore(ACCT, DEC, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "keys")), SRC)

c = st._open_live("message/message_0.db")
print("open_live ->", c)
tbl = "Msg_812a68e0dfcd495fd77d68ef4f686635"
print("table exists ->", c.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone())
rows = c.execute(
    'SELECT local_id, message_content, compress_content, WCDB_CT_message_content '
    'FROM "%s" WHERE local_type=3' % tbl).fetchall()
print("local_type=3 rows:", len(rows))
if rows:
    lid, mc, cpx, ct = rows[0]
    content = wcdb_decompress(mc or cpx, ct)
    txt = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
    print("lid", lid, "md5", re.search(r'md5="([0-9a-fA-F]{32})"', txt))
c.close()

# 现在跑完整 _ensure_cache 并打印中间状态
print("\n--- full _ensure_cache ---")
st._cache_map = None
st._ensure_cache()
print("cache_map size:", len(st._cache_map or {}))
for k, v in (st._cache_map or {}).items():
    print(" ", k, v)