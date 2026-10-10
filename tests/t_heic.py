# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core import media as m  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ACCT = "wxid_your_account_efcf"
SRC = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
st = m.MediaStore(ACCT, os.path.join(ROOT, "data", "decrypted"),
                  os.path.join(ROOT, "data", "keys"), SRC)
# 手动扫描 cache 打印所有 ImageTemp 文件头
cache = os.path.join(SRC, "cache")
for root, _d, files in os.walk(cache):
    if os.path.basename(root) != "ImageTemp":
        continue
    for f in files:
        p = os.path.join(root, f)
        with open(p, "rb") as fh:
            head = fh.read(32)
        print(f"{f[:40]}  head={head[:16].hex()}  ascii={head[:12]!r} "
              f"detect={m.detect_format(head)}")
        print(f"    detect_from_32={m.detect_format(head)}")
# 直接测 158 号文件
p1 = os.path.join(cache, "2026-10", "Message", "812a68e0dfcd495fd77d68ef4f686635",
                  "ImageTemp", "158_1790941059_mid_temp_convert")
if os.path.isfile(p1):
    with open(p1, "rb") as fh:
        h = fh.read(64)
    print(f"\n158 文件头: {h[:32].hex()}")
    print(f"  ascii: {h[:16]!r}")
    print(f"  detect: {m.detect_format(h)}")
    jpg = m.convert_to_jpeg(open(p1, 'rb').read())
    print(f"  转JPEG: {'OK '+str(len(jpg)) if jpg else '失败'}")
else:
    print("158 文件不存在")