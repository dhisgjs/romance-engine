# -*- coding: utf-8 -*-
"""全账号统计：消息里的图片 md5 vs 本地 attach 文件的匹配率（判断图片到底能不能显示）。"""
import hashlib
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACC = "wxid_your_account_efcf"
BASE = rf"D:\personal\Documents\xwechat_files\{ACC}"
mp = os.path.join("data", "decrypted", ACC, "message", "message_0.db")

# 本地所有 attach 文件名（去后缀）
attach = os.path.join(BASE, "msg", "attach")
local_files = set()
for root, _d, files in os.walk(attach):
    for f in files:
        if f.endswith(".dat"):
            local_files.add(f[:-4].lower())
print(f"本地 attach 文件数: {len(local_files)}")

conn = sqlite3.connect(f"file:{mp}?mode=ro&immutable=1", uri=True)
conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
import zstandard
dctx = zstandard.ZstdDecompressor()

# 统计所有图片消息 md5 与本地匹配
total = hit = 0
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
for tbl in tables:
    if re.fullmatch(r"Msg_[0-9a-f]{32}", tbl) is None:
        continue
    try:
        rows = conn.execute(f"SELECT message_content, WCDB_CT_message_content FROM '{tbl}' WHERE local_type % 4294967296 = 3").fetchall()
    except Exception:
        continue
    for content, ct in rows:
        if ct == 4:
            try:
                content = dctx.decompressobj().decompress(content)
            except Exception:
                pass
        text = (content or b"").decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        for m in re.findall(r'md5="([0-9a-fA-F]{32})"', text):
            total += 1
            md5 = m.lower()
            if md5 in local_files or md5 + "_t" in local_files or md5 + "_h" in local_files:
                hit += 1
conn.close()
print(f"图片消息 md5: {total}")
print(f"本地有文件的: {hit} ({hit/max(1,total)*100:.1f}%)")
print("\n结论：只有这些有本地文件的图片，在拿到媒体密钥后能显示")