# -*- coding: utf-8 -*-
"""检查联系人 remark 字段数据。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.models import Store

s = Store(os.path.join("data", "decrypted"), "wxid_your_account_efcf")
cs = s.contacts()
has_remark = sum(1 for c in cs if c.get("remark"))
has_alias = sum(1 for c in cs if c.get("alias"))
print("联系人总数:", len(cs))
print("有备注(remark):", has_remark)
print("有别名(alias):", has_alias)
n = 0
for c in cs:
    if c.get("remark"):
        print("  [备注]", repr(c["remark"]), "| [昵称]", repr(c.get("nick_name")),
              "| [别名]", repr(c.get("alias")), "|", c["username"])
        n += 1
        if n >= 5:
            break