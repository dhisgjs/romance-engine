# -*- coding: utf-8 -*-
"""debug：49 消息 content 解压 + extract_appmsg_title。"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.models import Store, extract_appmsg_title, wcdb_decompress

s = Store(os.path.join("data", "decrypted"), "wxid_your_account_efcf")
msgs = s.messages("wxid_peer_example")
n49 = [m for m in msgs if m["type"] == 49]

# 直接看第一条的 content 原始
m = n49[1]
print("text:", m["text"])
print("raw head:", m["raw"][:120])

# 手动调 extract_appmsg_title
print("extract:", extract_appmsg_title(m["raw"]))
