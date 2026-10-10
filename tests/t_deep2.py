# -*- coding: utf-8 -*-
"""深挖样本（复用能跑通的遍历方式）。"""
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import wcdb_decompress
from backend.core.media import detect_format, decrypt_v2_bytes
from Crypto.Cipher import AES

root = "data/decrypted/wxid_your_account_efcf"
acc = "wxid_your_account_efcf"
src = rf"D:\personal\Documents\xwechat_files\{acc}"
attach = os.path.join(src, "msg", "attach")

disk = {}
for r, _d, files in os.walk(attach):
    for f in files:
        if f.endswith(".dat"):
            disk.setdefault(re.sub(r"_([th])\.dat$", "", f)[:-4].lower(), []).append(os.path.join(r, f))

hl = os.path.join(root, "hardlink", "hardlink.db")
c = sqlite3.connect("file:" + hl.replace("\\", "/") + "?mode=ro&immutable=1", uri=True)
dir2id = {rid: u for rid, u in c.execute("SELECT rowid, username FROM dir2id")}
hl_map = {}
for md5, fname, d1, d2 in c.execute("SELECT md5, file_name, dir1, dir2 FROM image_hardlink_info_v4"):
    if fname and fname != "0":
        hl_map.setdefault(md5.lower(), []).append((fname, d1, d2))
c.close()

found = []
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
                    md5 = m.group(1).lower()
                    cands = list(disk.get(md5, []))
                    for fname, d1, d2 in hl_map.get(md5, []):
                        pth = os.path.join(attach, str(dir2id.get(d1, "?")), str(dir2id.get(d2, "?")), "Img", fname)
                        if os.path.isfile(pth):
                            cands.append(pth)
                        cands.extend(disk.get(re.sub(r"_([th])\.dat$", "", fname)[:-4].lower(), []))
                    if cands:
                        found.append((md5, k.group(1).lower(), cands[0]))
            if len(found) >= 5:
                break
        if len(found) >= 5:
            break
    cc.close()
    if len(found) >= 5:
        break

print(f"可测样本: {len(found)}")
for md5, aeshex, pth in found:
    print("=" * 60)
    print(f"md5={md5}  aeskey={aeshex}  file={os.path.basename(pth)}")
    with open(pth, "rb") as fh:
        data = fh.read()
    if data[:6] != b"\x07\x08V2\x08\x07":
        print(f"  非V2! head={data[:16].hex()}")
        continue
    a = int.from_bytes(data[6:10], "little")
    x = int.from_bytes(data[10:14], "little")
    print(f"  size={len(data)} aes={a} xor={x}")
    for name, key in (
        ("hex16", bytes.fromhex(aeshex)),
        ("hex32x2", bytes.fromhex(aeshex) * 2),
        ("ascii前16", aeshex[:16].encode()),
        ("ascii32", aeshex.encode()),
    ):
        if len(key) not in (16, 24, 32):
            continue
        r = decrypt_v2_bytes(data, key)
        print(f"    {name}(len{len(key)}): {'OK ' + r[1] if r else 'fail'}")
    # 逐块找魔数
    key = bytes.fromhex(aeshex)
    try:
        cipher = AES.new(key, AES.MODE_ECB)
        hits = []
        for off in range(0, min(len(data), 8192) - 15, 16):
            dec = cipher.decrypt(data[off:off + 16])
            if detect_format(dec) != "bin":
                hits.append((off, dec[:8].hex()))
            if len(hits) >= 3:
                break
        print(f"    逐块魔数命中: {hits}")
    except Exception as e:
        print(f"    逐块异常 {e}")