# -*- coding: utf-8 -*-
"""验证完整图片映射链：消息XML md5 → hardlink.db → 实际文件路径 → 文件存在？"""
import hashlib
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACC = "wxid_your_account_efcf"
BASE = rf"D:\personal\Documents\xwechat_files\{ACC}"
mp = os.path.join("data", "decrypted", ACC, "message", "message_0.db")
hl = os.path.join("data", "decrypted", ACC, "hardlink", "hardlink.db")

conn = sqlite3.connect(f"file:{mp}?mode=ro&immutable=1", uri=True)
conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
hlconn = sqlite3.connect(f"file:{hl}?mode=ro&immutable=1", uri=True)
hlconn.text_factory = lambda b: b.decode("utf-8", errors="replace")
import zstandard
dctx = zstandard.ZstdDecompressor()

# hardlink: md5 -> (file_name, dir1, dir2)；dir2id: rowid -> 目录名
hl_map = {}
for md5, fname, d1, d2 in hlconn.execute("SELECT md5, file_name, dir1, dir2 FROM image_hardlink_info_v4"):
    hl_map[md5.lower()] = (fname, d1, d2)
dir2id = {rid: u for rid, u in hlconn.execute("SELECT rowid, username FROM dir2id")}
print(f"hardlink 图片映射: {len(hl_map)} 条")

# 查小宝最近的图片消息，走完整映射
t = "Msg_" + hashlib.md5(b"wxid_peer_example").hexdigest()[:32]
rows = conn.execute(
    f"SELECT message_content, WCDB_CT_message_content FROM '{t}' "
    f"WHERE local_type % 4294967296 = 3 LIMIT 10").fetchall()
hit = 0
for content, ct in rows:
    if ct == 4:
        try:
            content = dctx.decompressobj().decompress(content)
        except Exception:
            pass
    text = (content or b"").decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
    m = re.search(r'md5="([0-9a-fA-F]{32})"', text)
    if not m:
        continue
    md5 = m.group(1).lower()
    if md5 not in hl_map:
        print(f"  ✗ md5不在hardlink: {md5[:12]}")
        continue
    fname, d1, d2 = hl_map[md5]
    # 还原路径
    p = os.path.join(BASE, "msg", "attach", dir2id.get(d1, "?"), dir2id.get(d2, "?"), "Img", fname)
    exists = os.path.isfile(p)
    if exists:
        hit += 1
    print(f"  {'✓' if exists else '✗'} {fname} -> {os.path.relpath(p, BASE)[:80]} {'存在' if exists else '不存在'}")
conn.close()
hlconn.close()
print(f"\n命中: {hit}/10（这些图片拿到密钥后能显示）")