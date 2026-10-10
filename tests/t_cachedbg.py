# -*- coding: utf-8 -*-
"""诊断 cache->md5 映射为何 0 命中。"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core import media as media_mod  # noqa: E402
from backend.core.models import wcdb_decompress  # noqa: E402

ACCT = "wxid_your_account_efcf"
SRC = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
DEC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "decrypted"))
CACHE = os.path.join(SRC, "cache")

print("step1: 扫描 cache 收集 (talker, local_id)")
by_key = {}
for root, _dirs, files in os.walk(CACHE):
    kind = os.path.basename(root)
    if kind not in ("Thumb", "ImageTemp"):
        continue
    rel = os.path.relpath(root, CACHE).split(os.sep)
    if len(rel) < 3 or rel[1] != "Message":
        print(f"  跳过路径层级不符: {rel}")
        continue
    talker = rel[2].lower()
    for f in files:
        m = re.match(r"(\d+)_\d+_[A-Za-z0-9_]+", f)
        if not m:
            continue
        full = os.path.join(root, f)
        try:
            if media_mod.detect_format(media_mod._read_head(full)) == "bin":
                print(f"  非图片: {rel}")
                continue
        except OSError:
            continue
        by_key[(talker, int(m.group(1)))] = (full, kind)
print(f"  by_key = {len(by_key)}")
for k in list(by_key)[:15]:
    print(f"    {k}")

print("\nstep2: 查 Msg_ 表")
db = os.path.join(DEC, ACCT, "message", "message_0.db")
c = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
c.text_factory = lambda b: b.decode("utf-8", errors="replace")
for (talker, lid), (path, kind) in list(by_key.items())[:15]:
    tbl = f"Msg_{talker}"
    has = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tbl,)).fetchone()
    print(f"  {talker[:12]}/{lid} [{kind}] 表存在={bool(has)}")
    if not has:
        continue
    try:
        row = c.execute(
            f'SELECT local_type, message_content, compress_content, WCDB_CT_message_content '
            f'FROM "{tbl}" WHERE local_id=?', (lid,)).fetchone()
    except Exception as e:
        print(f"    查询失败 {e}")
        continue
    print(f"    row={'有' if row else '无'} local_type={row[0] if row else '-'}")
    if not row:
        continue
    content = wcdb_decompress(row[1] or row[2], row[3])
    txt = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    m = re.search(r'md5="([0-9a-fA-F]{32})"', txt)
    print(f"    md5={m.group(1) if m else '无'}  {txt[:120]!r}")
c.close()