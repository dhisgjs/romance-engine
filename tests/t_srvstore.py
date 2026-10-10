# -*- coding: utf-8 -*-
"""模拟服务端 _media_store 的构造，验证 cache 命中。"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import backend.app as A  # noqa: E402

ACC = "wxid_your_account_efcf"
st = A._media_store(ACC)
print("source_base =", st.source_base)
print("decrypted_root =", st.decrypted_root)
print("keys_dir =", st.keys_dir)
ok = st._ensure_cache()
print("_ensure_cache ->", ok, "map size", len(st._cache_map or {}))
for md5 in ("38fcb13ce473eee042b6b219e7edcbbd", "1b455c418160723eebd0d70fc16a43a5"):
    p = st.resolve_cache_image(md5)
    print(f"  resolve_cache_image({md5[:12]}) -> {p}")
    print(f"  resolve_image({md5[:12]})      -> {st.resolve_image(md5)}")