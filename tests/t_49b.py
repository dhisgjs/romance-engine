# -*- coding: utf-8 -*-
"""看 type49 在修复后 content/source/raw 的实际内容。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import Store

s = Store(os.path.join("data", "decrypted"), "wxid_your_account_efcf")
msgs = s.messages("wxid_peer_example")
n49 = [m for m in msgs if m["type"] == 49]
print(f"49 消息 {len(n49)} 条")
for m in n49[:3]:
    print("  text:", repr(m["text"][:100]))
    print("  raw :", repr((m.get("raw") or "")[:150]))
    print("  ---")