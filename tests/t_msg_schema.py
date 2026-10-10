# -*- coding: utf-8 -*-
import os
import sqlite3

msg_db = os.path.join("data", "decrypted", "wxid_your_account_efcf", "message", "message_0.db")
c = sqlite3.connect(f"file:{msg_db}?mode=ro&immutable=1", uri=True)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
with open("out_tmp16.txt", "w", encoding="utf-8") as f:
    f.write("tables: " + ", ".join(tabs) + "\n")
    for t in tabs:
        cols = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]
        f.write(f"{t}: {cols}\n")
c.close()