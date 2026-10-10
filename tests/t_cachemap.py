# -*- coding: utf-8 -*-
"""验证 MediaStore.resolve_cache_image 能否把 cache 明文图映射到 md5。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core import media as media_mod  # noqa: E402

ACCT = "wxid_your_account_efcf"
SRC = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"
DEC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "decrypted"))
KEYS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "keys"))

st = media_mod.MediaStore(ACCT, DEC, KEYS, SRC)
ok = st._ensure_cache()
print(f"_ensure_cache -> {ok}")
print(f"索引到 {len(st._cache_map or {})} 个 md5")
for md5, (p, kind) in list((st._cache_map or {}).items()):
    sz = os.path.getsize(p)
    fmt = media_mod.detect_format(media_mod._read_head(p))
    print(f"  {md5} {kind} {fmt} {sz}B")
    print(f"     {os.path.relpath(p, SRC)}")
    got = st.resolve_cache_image(md5)
    print(f"     resolve -> {'OK' if got == p else 'FAIL'}")

lines = [f"索引 {len(st._cache_map or {})} 个 md5"]
for md5, (p, kind) in (st._cache_map or {}).items():
    lines.append(f"{md5} {kind} {os.path.getsize(p)}B {os.path.relpath(p, SRC)}")
with open(os.path.join(os.path.dirname(__file__), "..", "out_tmp41.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))