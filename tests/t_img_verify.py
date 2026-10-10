# -*- coding: utf-8 -*-
"""严格验证刚提取的密钥：对全部样本解密，必须全部是图片格式。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Crypto.Cipher import AES

ACC = "wxid_your_account_efcf"
attach = rf"D:\personal\Documents\xwechat_files\{ACC}\msg\attach"
kf = os.path.join("data", "keys", f"{ACC}.image_key")
key = bytes.fromhex(open(kf).read().strip())
print("待验证密钥:", key.hex(), repr(key))

MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")
cipher = AES.new(key, AES.MODE_ECB)

ok = bad = 0
for root, _d, files in os.walk(attach):
    for f in files:
        if not f.endswith(".dat"):
            continue
        p = os.path.join(root, f)
        try:
            with open(p, "rb") as fh:
                head = fh.read(31)
            if head[:6] != b"\x07\x08V2\x08\x07":
                continue
            dec = cipher.decrypt(head[15:31])
            is_img = any(dec.startswith(m) for m in MAGICS) or (dec[:4]==b"RIFF" and dec[8:12]==b"WEBP")
            if is_img:
                ok += 1
            else:
                bad += 1
                print(f"  ✗ 非图片: {f} -> {dec[:8].hex()}")
        except OSError:
            pass
print(f"\n验证: {ok} 个命中图片格式, {bad} 个失败")
print("结果:", "PASS（密钥有效！图片可解密）" if bad == 0 and ok > 0 else "FAIL（误判）")