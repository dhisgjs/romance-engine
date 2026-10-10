# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core import memscan  # noqa: E402

ACCT = "wxid_your_account_efcf"
print("find_data_dirs ->", memscan.find_data_dirs())
for d in memscan.find_data_dirs():
    print(f"  {d}  accounts={memscan.list_accounts(d)[:5]}")
print("list_accounts all ->")
for d in memscan.find_data_dirs():
    print(" ", d, memscan.list_accounts(d))