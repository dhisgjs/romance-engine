# -*- coding: utf-8 -*-
"""端到端验证 /api/media：明文缓存图 + HEIC 转码。"""
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core import media as m  # noqa: E402

ACCT = "wxid_your_account_efcf"
SRC = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
st = m.MediaStore(ACCT, os.path.join(ROOT, "data", "decrypted"),
                  os.path.join(ROOT, "data", "keys"), SRC)
st._ensure_cache()
for md5, (p, kind) in (st._cache_map or {}).items():
    with open(p, "rb") as f:
        data = f.read()
    fmt = m.detect_format(data[:32])
    print(f"{md5} {kind} {fmt} {len(data)}B")
    if fmt in m.NEEDS_CONVERT:
        jpg = m.convert_to_jpeg(data)
        print(f"  -> 转 JPEG: {'OK ' + str(len(jpg)) + 'B' if jpg else '失败'}")
        if jpg:
            print(f"     头 {jpg[:4].hex()} 尾 {jpg[-2:].hex()}")
            from PIL import Image
            im = Image.open(io.BytesIO(jpg))
            print(f"     尺寸 {im.size} 模式 {im.mode}")