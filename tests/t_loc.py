# -*- coding: utf-8 -*-
"""定位 cache 明文图对应消息：查 local_id 在 message_0 / biz_message_0 各 Msg_ 表的记录。
确认这些 local_id 的类型，找出与 .dat 的对应关系。
"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from core.models import wcdb_decompress  # noqa: E402

DEC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "decrypted",
                                   "wxid_your_account_efcf"))
# (talker_md5, local_id) 从 cache 观察到
TARGETS = [
    ("0bbf098660a4932fd8fdd9af9367e0b4", 1373),
    ("3afde4ed07138fd8c28e8b25e2dafb79", 4600),
    ("4c3ae71d0d6978d0671e1d69393460d6", 8650),
    ("92ab053817c21d1af3da8cb3f2a663ab", 859),
    ("92ab053817c21d1af3da8cb3f2a663ab", 1075),
    ("92ab053817c21d1af3da8cb3f2a663ab", 1166),
    ("a76a15421975ced44307be099f8cc7f3", 203),
    ("a76a15421975ced44307be099f8cc7f3", 205),
    ("a76a15421975ced44307be099f8cc7f3", 206),
    ("c364ee68f854d50d3fa0a1196d0eeea9", 3046),
    ("c364ee68f854d50d3fa0a1196d0eeea9", 3053),
    ("c7b34a2e0646ae567392cf5c5aada148", 85),
]

out = []
for db in ("message/message_0.db", "message/biz_message_0.db"):
    p = os.path.join(DEC, db).replace("\\", "/")
    cc = sqlite3.connect("file:" + p + "?mode=ro", uri=True)
    cc.text_factory = lambda b: b.decode("utf-8", errors="replace")
    tabs = [r[0] for r in cc.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
    tab_by_talker = {t[4:].lower(): t for t in tabs}
    out.append(f"== {db} 共 {len(tabs)} 表 ==")
    for talker, lid in TARGETS:
        t = tab_by_talker.get(talker)
        if not t:
            out.append(f"  {talker[:12]} {lid}: 无此表")
            continue
        cols = [r[1] for r in cc.execute('PRAGMA table_info("%s")' % t)]
        if "local_id" not in cols:
            out.append(f"  {talker[:12]} {lid}: 表 {t} 无 local_id")
            continue
        row = cc.execute('SELECT * FROM "%s" WHERE local_id=?' % t, (lid,)).fetchone()
        if not row:
            out.append(f"  {talker[:12]} {lid}: local_id 不存在")
            continue
        colmap = {c[1]: i for i, c in enumerate(cc.execute('PRAGMA table_info("%s")' % t))}
        lt = row[colmap.get("local_type", 0)]
        mc = row[colmap.get("message_content")]
        cpx = row[colmap.get("compress_content")]
        ct = row[colmap.get("WCDB_CT_message_content")]
        try:
            content = wcdb_decompress(mc or cpx, ct)
        except Exception:
            content = b""
        txt = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
        md5m = re.search(r'md5="([0-9a-fA-F]{32})"', txt)
        aesm = re.search(r'aeskey="([0-9a-fA-F]{32})"', txt)
        out.append(f"  {talker[:12]} {lid}: local_type={lt} md5={md5m.group(1) if md5m else '-'}"
                   f" aeskey={aesm.group(1) if aesm else '-'} content={txt[:100]!r}")
    cc.close()

text = "\n".join(out)
with open("out_tmp40.txt", "w", encoding="utf-8") as fh:
    fh.write(text)
print(text)