# -*- coding: utf-8 -*-
"""诊断 resolve_image 为何找不到文件。"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress

root = "data/decrypted/wxid_your_account_efcf"
acc = "wxid_your_account_efcf"
src = rf"D:\personal\Documents\xwechat_files\{acc}"

# 1) 硬链接库内容
hl = os.path.join(root, "hardlink", "hardlink.db")
c = sqlite3.connect("file:" + hl.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
dir2id = {rid: u for rid, u in c.execute("SELECT rowid, username FROM dir2id")}
print("dir2id 条目:", list(dir2id.items())[:10])
rows = list(c.execute("SELECT md5, file_name, dir1, dir2 FROM image_hardlink_info_v4 LIMIT 10"))
print("image表样例:")
for r in rows:
    print("  ", r)
c.close()

# 2) 磁盘实际目录
attach = os.path.join(src, "msg", "attach")
print("\n磁盘 attach 下的前5个目录:")
n = 0
for root_d, dirs, files in os.walk(attach):
    if files:
        print("  ", root_d.replace(src, "..."), f"({len(files)}文件)")
        n += 1
    if n >= 5:
        break

# 3) 取一个 aeskey 试试手工拼路径
msg_dir = os.path.join(root, "message")
found = None
for fn in sorted(os.listdir(msg_dir)):
    if not fn.endswith(".db"):
        break
    p = os.path.join(msg_dir, fn).replace("\\", "/")
    cc = sqlite3.connect("file:" + p + "?mode=ro&immutable=1", uri=True)
    cc.text_factory = lambda b: b.decode("utf-8", errors="replace")
    for (t,) in cc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"):
        cols = [r[1] for r in cc.execute('PRAGMA table_info("' + t + '")')]
        if "message_content" not in cols:
            continue
        for mc, ccx, ct in cc.execute('SELECT message_content, compress_content, WCDB_CT_message_content FROM "' + t + '" LIMIT 50'):
            try:
                content = wcdb_decompress(mc or ccx, ct)
            except Exception:
                continue
            if content and "<img" in content:
                mm = re.search(r'md5="([0-9a-fA-F]{32})"', content)
                kk = re.search(r'aeskey="([0-9a-fA-F]{32})"', content)
                if mm and kk:
                    found = (mm.group(1).lower(), kk.group(1).lower())
                    break
        if found:
            break
    cc.close()
    if found:
        break

print("\n样本 md5/aeskey:", found)
if found:
    md5, aeshex = found
    c = sqlite3.connect("file:" + hl.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
    recs = list(c.execute("SELECT md5, file_name, dir1, dir2 FROM image_hardlink_info_v4 WHERE md5=?", (md5,)))
    print("该md5的hardlink记录:", recs)
    for md5h, fname, d1, d2 in recs:
        u1, u2 = dir2id.get(d1), dir2id.get(d2)
        pth = os.path.join(attach, str(u1), str(u2), "Img", fname or "")
        print("  拼出路径:", pth)
        print("  存在?", os.path.isfile(pth))
    c.close()