# -*- coding: utf-8 -*-
"""测试 key = 文件名(32hex) 假设：遍历所有 V2 文件。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.media import decrypt_v2_bytes

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
V2 = b"\x07\x08V2\x08\x07"
ok = fail = total = 0
examples = []
for r, _d, files in os.walk(attach):
    for f in files:
        if not f.endswith(".dat"):
            continue
        p = os.path.join(r, f)
        base = os.path.splitext(f)[0].lower()
        keyname = re.sub(r"_(t|h)$", "", base)
        if not re.fullmatch(r"[0-9a-f]{32}", keyname):
            continue
        try:
            with open(p, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if data[:6] != V2:
            continue
        total += 1
        good = False
        for key in (bytes.fromhex(keyname), keyname.encode("latin-1")):
            if len(key) not in (16, 32):
                continue
            res = decrypt_v2_bytes(data, key)
            if res:
                ok += 1
                good = True
                if len(examples) < 5:
                    examples.append(f"OK {f} key={key.hex()} {res[1]} {len(res[0])}B")
                break
        if not good:
            fail += 1

out = [f"total={total} ok={ok} fail={fail}"] + examples
text = "\n".join(out)
with open("out_tmp25.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)