# -*- coding: utf-8 -*-
"""把 cache 里的明文图和 msg/attach 里的加密 .dat 配对。

cache 结构: <月>\Message\<talker_md5>\<Thumb|ImageTemp|Bubble>\<local_id>_<ts>_<kind>[.jpg]
消息表: Msg_<talker_md5>(local_id, ...) -> XML 里 md5="..."
hardlink: image_hardlink_info_v4(md5, file_name, dir1, dir2) + dir2id(rowid->username)
文件: attach/<talker>/<YYYY-MM>/Img/<file_name>
"""
import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from core.models import wcdb_decompress  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ACCT = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
DEC = os.path.join(ROOT, "data", "decrypted", "wxid_your_account_efcf")
ATTACH = os.path.join(ACCT, "msg", "attach")
CACHE = os.path.join(ACCT, "cache")
V2 = b"\x07\x08V2\x08\x07"
MAGICS = (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb",
          b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM", b"RIFF", b"II*\x00", b"MM\x00*")


def is_img(d):
    return d.startswith(MAGICS) or (len(d) >= 12 and d[4:8] == b"ftyp")


def build_file_index():
    """attach 下所有 .dat 的路径索引：basename(去_h/_t/_b 后缀) -> [(path, variant)]"""
    idx = defaultdict(list)
    for r, _d, fl in os.walk(ATTACH):
        for f in fl:
            if not f.endswith(".dat"):
                continue
            base = f[:-4]
            var = "full"
            for suf in ("_h", "_t", "_b", "_hd"):
                if base.endswith(suf):
                    base = base[:-len(suf)]
                    var = suf[1:]
                    break
            idx[base].append((os.path.join(r, f), var))
    return idx


def hardlink_map():
    c = sqlite3.connect("file:" + os.path.join(DEC, "hardlink", "hardlink.db").replace("\\", "/")
                        + "?mode=ro", uri=True)
    dir2id = {rid: u for rid, u in c.execute("SELECT rowid, username FROM dir2id")}
    m = {}
    for md5, fn, d1, d2 in c.execute(
            "SELECT md5, file_name, dir1, dir2 FROM image_hardlink_info_v4"):
        if fn and fn != "0":
            m.setdefault(md5.lower(), []).append((fn, d1, d2))
    c.close()
    return m, dir2id


def msg_index():
    """(talker_md5, local_id) -> (md5, create_time)"""
    p = os.path.join(DEC, "message", "message_0.db").replace("\\", "/")
    cc = sqlite3.connect("file:" + p + "?mode=ro", uri=True)
    cc.text_factory = lambda b: b.decode("utf-8", errors="replace")
    res = {}
    tabs = [r[0] for r in cc.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
    for t in tabs:
        talker = t[4:]
        cols = [r[1] for r in cc.execute('PRAGMA table_info("%s")' % t)]
        if "message_content" not in cols:
            continue
        for lid, mc, cpx, ct in cc.execute(
                'SELECT local_id, message_content, compress_content, WCDB_CT_message_content '
                'FROM "%s" WHERE local_type=3' % t):
            try:
                content = wcdb_decompress(mc or cpx, ct)
            except Exception:
                continue
            if not content or "<img" not in content:
                continue
            m = re.search(r'md5="([0-9a-fA-F]{32})"', content)
            if m:
                res[(talker.lower(), lid)] = m.group(1).lower()
    cc.close()
    return res


def main():
    lines = []
    lines.append("建立索引...")
    files = build_file_index()
    lines.append(f"  attach .dat: {sum(len(v) for v in files.values())} 文件, {len(files)} 基名")
    hl, dir2id = hardlink_map()
    lines.append(f"  hardlink image 行: {len(hl)}")
    mi = msg_index()
    lines.append(f"  图片消息 (talker,local_id)->md5: {len(mi)}")

    lines.append("")
    lines.append("cache 明文图清单与配对:")
    pairs = []
    for r, _d, fl in os.walk(CACHE):
        for f in fl:
            p = os.path.join(r, f)
            try:
                with open(p, "rb") as fh:
                    head = fh.read(16)
            except OSError:
                continue
            if not is_img(head):
                continue
            rel = os.path.relpath(p, CACHE)
            parts = rel.replace("/", "\\").split("\\")
            if len(parts) < 4 or parts[1] != "Message":
                continue
            talker = parts[2].lower()
            m = re.match(r"(\d+)_(\d+)_([a-z]+)", f)
            if not m:
                lines.append(f"  [无法解析文件名] {rel}")
                continue
            lid = int(m.group(1))
            md5 = mi.get((talker, lid))
            lines.append(f"\n  {rel}")
            lines.append(f"    size={os.path.getsize(p)} 格式={head[:4].hex()} local_id={lid} md5={md5}")
            if not md5:
                continue
            cands = []
            for fn, d1, d2 in hl.get(md5, []):
                pp = os.path.join(ATTACH, str(dir2id.get(d1, "?")), str(dir2id.get(d2, "?")), "Img", fn)
                if os.path.isfile(pp):
                    cands.append(pp)
            for base, vv in files.get(md5, []):
                cands += [x for x, _v in vv]
            if not cands:
                lines.append("    未找到对应 .dat")
                continue
            for cp in cands[:4]:
                with open(cp, "rb") as fh:
                    hd = fh.read(64)
                if hd[:6] == V2:
                    a = int.from_bytes(hd[6:10], "little")
                    x = int.from_bytes(hd[10:14], "little")
                    lines.append(f"    V2 {os.path.basename(cp)} aes={a} xor={x} size={os.path.getsize(cp)}")
                    pairs.append((p, cp))
                else:
                    lines.append(f"    非V2 {os.path.basename(cp)} head={hd[:8].hex()} size={os.path.getsize(cp)}")

    lines.append("")
    lines.append(f"可配对 V2 文件 {len(pairs)} 对")
    text = "\n".join(lines)
    with open("out_tmp39.txt", "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()