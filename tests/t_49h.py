# -*- coding: utf-8 -*-
"""找有 title 的 49 消息，验证是否显示成功。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import Store, extract_appmsg_title

s = Store(os.path.join("data", "decrypted"), "wxid_your_account_efcf")
n49 = [m for m in s.messages("wxid_peer_example") if m["type"] == 49]

has_title = [m for m in n49 if re.search(r"<title>[^<]{2,}</title>", m.get("raw") or "")]
print(f"49 消息 {len(n49)}，其中有标题的 {len(has_title)}")
ok = bad = 0
for m in has_title[:10]:
    raw = m.get("raw") or ""
    t = extract_appmsg_title(raw)
    shown = m["text"]
    if shown == t and not shown.startswith("["):
        ok += 1
    else:
        bad += 1
        print(f"  ✗ 提取={t[:30]!r} 显示={shown[:30]!r} raw={raw[:60]!r}")
print(f"显示正常 {ok} / 异常 {bad}")
print("结果:", "PASS" if bad == 0 else "FAIL")