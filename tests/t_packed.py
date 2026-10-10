# -*- coding: utf-8 -*-
"""查两个可能直接含本地图片密钥的位置：
1) 消息表 packed_info_data 列（type=3 图片消息）
2) hardlink.db 全部表的完整 schema 与 blob 列
"""
import binascii
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from core.models import wcdb_decompress  # noqa: E402

acct = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
out = []

out.append("=" * 60)
out.append("1) hardlink.db 全表 schema")
out.append("=" * 60)
hl = os.path.join(os.path.dirname(__file__), "..", "data", "decrypted",
                  "wxid_your_account_efcf", "hardlink", "hardlink.db")
hl = os.path.abspath(hl)
c = sqlite3.connect("file:" + hl.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
for t in tabs:
    cols = c.execute('PRAGMA table_info("%s")' % t).fetchall()
    n = c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
    out.append(f"\n-- {t} ({n} 行)")
    for ci in cols:
        out.append(f"   {ci[1]:24} {ci[2]}")
    # blob 列样例
    for ci in cols:
        if "BLOB" in (ci[2] or "").upper():
            rows = c.execute('SELECT "%s" FROM "%s" WHERE "%s" IS NOT NULL LIMIT 3'
                             % (ci[1], t, ci[1])).fetchall()
            for i, (v,) in enumerate(rows):
                b = bytes(v)
                out.append(f"   [{ci[1]}] len={len(b)} {b[:48].hex()} ascii={b[:32]!r}")
c.close()

out.append("")
out.append("=" * 60)
out.append("2) 图片消息的 packed_info_data")
out.append("=" * 60)
msgdir = os.path.join(os.path.dirname(__file__), "..", "data", "decrypted",
                      "wxid_your_account_efcf", "message")
msgdir = os.path.abspath(msgdir)
shown = 0
for fn in sorted(os.listdir(msgdir)):
    if not fn.endswith(".db"):
        continue
    p = os.path.join(msgdir, fn).replace("\\", "/")
    try:
        cc = sqlite3.connect("file:" + p + "?mode=ro", uri=True)
        cc.text_factory = lambda b: b.decode("utf-8", errors="replace")
        ts = [r[0] for r in cc.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
    except Exception:
        continue
    for t in ts:
        cols = [r[1] for r in cc.execute('PRAGMA table_info("%s")' % t)]
        if "packed_info_data" not in cols:
            continue
        sel = ",".join('"%s"' % x for x in ("local_id", "local_type", "packed_info_data",
                                             "message_content", "compress_content",
                                             "WCDB_CT_message_content"))
        try:
            rows = cc.execute("SELECT %s FROM \"%s\" WHERE local_type=3 LIMIT 200" % (sel, t)).fetchall()
        except Exception:
            continue
        for row in rows:
            if shown >= 8:
                break
            lid, lt, pid, mc, cpx, ct = row
            try:
                content = wcdb_decompress(mc or cpx, ct)
            except Exception:
                content = ""
            pid_b = bytes(pid) if pid is not None else b""
            md5m = re.search(r'md5="([0-9a-fA-F]{32})"', content or "")
            out.append(f"\nlocal_id={lid} packed_info_data len={len(pid_b)}")
            out.append(f"  hex[:160] = {pid_b[:160].hex()}")
            printable = bytes(b for b in pid_b if 32 <= b < 127)
            out.append(f"  ascii = {printable[:120]!r}")
            out.append(f"  md5 = {md5m.group(1) if md5m else '-'}")
            shown += 1
    cc.close()
    if shown >= 8:
        break

text = "\n".join(out)
with open("out_tmp38.txt", "w", encoding="utf-8") as fh:
    fh.write(text)
print(text[:8000])