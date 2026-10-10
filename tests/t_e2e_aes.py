# -*- coding: utf-8 -*-
"""端到端：用 XML 的 (md5, aeskey) 找图并解密。含 md5_hash 兜底匹配。"""
import os
import re
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress
from backend.core.media import decrypt_v2_bytes, detect_format

root = "data/decrypted/wxid_your_account_efcf"
acc = "wxid_your_account_efcf"
src = rf"D:\personal\Documents\xwechat_files\{acc}"
attach = os.path.join(src, "msg", "attach")

# --- 建立磁盘文件索引：文件名(去后缀) -> 路径 ---
disk = {}
for r, _d, files in os.walk(attach):
    for f in files:
        if f.endswith(".dat"):
            base = re.sub(r"_([th])\.dat$", "", f)
            disk.setdefault(base[:-4].lower(), []).append(os.path.join(r, f))
print(f"磁盘图片索引: {len(disk)} 个唯一名")

# --- hardlink 索引 ---
hl = os.path.join(root, "hardlink", "hardlink.db")
c = sqlite3.connect("file:" + hl.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
dir2id = {rid: u for rid, u in c.execute("SELECT rowid, username FROM dir2id")}
hl_map = {}
for md5, fname, d1, d2 in c.execute("SELECT md5, file_name, dir1, dir2 FROM image_hardlink_info_v4"):
    if fname and fname != "0":
        hl_map.setdefault(md5.lower(), []).append((fname, d1, d2))
c.close()
print(f"hardlink 索引: {len(hl_map)} 个md5")

# --- 收集 (md5, aeskey) ---
pairs = []
msg_dir = os.path.join(root, "message")
for fn in sorted(os.listdir(msg_dir)):
    if not fn.endswith(".db"):
        continue
    p = os.path.join(msg_dir, fn).replace("\\", "/")
    cc = sqlite3.connect("file:" + p + "?mode=ro&immutable=1", uri=True)
    cc.text_factory = lambda b: b.decode("utf-8", errors="replace")
    for (t,) in cc.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'"):
        cols = [r[1] for r in cc.execute('PRAGMA table_info("' + t + '")')]
        if "message_content" not in cols:
            continue
        try:
            rows = cc.execute(
                'SELECT message_content, compress_content, WCDB_CT_message_content FROM "' + t + '"').fetchall()
        except Exception:
            continue
        for mc, ccx, ct in rows:
            try:
                content = wcdb_decompress(mc or ccx, ct)
            except Exception:
                continue
            if content and "<img" in content:
                m = re.search(r'md5="([0-9a-fA-F]{32})"', content)
                k = re.search(r'aeskey="([0-9a-fA-F]{32})"', content)
                if m and k:
                    pairs.append((m.group(1).lower(), k.group(1).lower()))
    cc.close()
print(f"(md5,aeskey) 对: {len(pairs)}")

stats = Counter()
ok_rows = []
for md5, aeshex in pairs:
    key = bytes.fromhex(aeshex)
    if len(key) != 16:
        stats["key格式错"] += 1
        continue
    # 定位文件：先磁盘索引（用 md5 作为文件名），再 hardlink
    cands = list(disk.get(md5, []))
    for fname, d1, d2 in hl_map.get(md5, []):
        pth = os.path.join(attach, str(dir2id.get(d1, "?")), str(dir2id.get(d2, "?")), "Img", fname)
        if os.path.isfile(pth):
            cands.append(pth)
        base = re.sub(r"_([th])\.dat$", "", fname)[:-4].lower()
        cands.extend(disk.get(base, []))
    if not cands:
        stats["未找到文件"] += 1
        continue
    stats["找到文件"] += 1
    for pth in cands:
        try:
            with open(pth, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        r = decrypt_v2_bytes(data, key)
        if r:
            stats["解密成功"] += 1
            if len(ok_rows) < 10:
                ok_rows.append(f"  ✓ md5={md5[:12]} file={os.path.basename(pth)} aeskey={aeshex}({key!r}) -> {r[1]} {len(r[0])}B")
            break
    else:
        stats["解密失败"] += 1

print("统计:", dict(stats))
print("\n".join(ok_rows))
with open("out_tmp24.txt", "w", encoding="utf-8") as f:
    f.write(f"统计: {dict(stats)}\n")
    f.write(f"磁盘索引 {len(disk)}, hardlink {len(hl_map)}, pairs {len(pairs)}\n\n")
    f.write("\n".join(ok_rows))