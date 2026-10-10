# -*- coding: utf-8 -*-
"""检查小宝聊天里的图片消息：本地文件 / 密钥 / 可显示性。"""
import hashlib
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import memscan, media as media_mod

ACC = "wxid_your_account_efcf"
BASE = rf"D:\personal\Documents\xwechat_files\{ACC}"
mp = os.path.join("data", "decrypted", ACC, "message", "message_0.db")

# 小宝的图片消息
t = "Msg_" + hashlib.md5(b"wxid_peer_example").hexdigest()[:32]
conn = sqlite3.connect(f"file:{mp}?mode=ro&immutable=1", uri=True)
conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
import zstandard
dctx = zstandard.ZstdDecompressor()

img_msgs = conn.execute(
    f"SELECT local_id, create_time, message_content, WCDB_CT_message_content "
    f"FROM '{t}' WHERE local_type % 4294967296 = 3 ORDER BY create_time DESC LIMIT 10").fetchall()
print(f"小宝最近图片消息: {len(img_msgs)} 条")
md5s = []
for lid, ts, content, ct in img_msgs:
    if ct == 4:
        try:
            content = dctx.decompressobj().decompress(content)
        except Exception:
            pass
    text = (content or b"").decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
    m = re.search(r'md5="([0-9a-fA-F]{32})"', text)
    if m:
        md5s.append(m.group(1).lower())
conn.close()

print(f"提取到 md5: {len(md5s)} 个")
# 检查本地 attach 是否有这些图（硬链接/直接路径）
attach = os.path.join(BASE, "msg", "attach")
found = 0
for md5 in md5s[:5]:
    for root, _d, files in os.walk(attach):
        if any(md5 in f for f in files):
            found += 1
            print(f"  本地有: {md5[:12]} ({[f for f in files if md5 in f][:2]})")
            break
    else:
        print(f"  本地无: {md5[:12]}")

# 媒体密钥状态
kf = os.path.join("data", "keys", f"{ACC}.image_key")
print(f"\n媒体密钥文件: {'存在' if os.path.isfile(kf) else '不存在'}")
if os.path.isfile(kf):
    print("key:", open(kf).read().strip()[:16])