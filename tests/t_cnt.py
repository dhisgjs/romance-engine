# -*- coding: utf-8 -*-
import sqlite3

p = r"data\decrypted\wxid_your_account_efcf\message\message_0.db"
uri = "file:" + p.replace("\\", "/") + "?mode=ro&immutable=1"
c = sqlite3.connect(uri, uri=True)
tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
with open("out_tmp20.txt", "w", encoding="utf-8") as f:
    f.write(f"Msg表数: {len(tabs)}\n")
    for t in tabs[:8]:
        try:
            n = c.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        except Exception as e:
            n = f"ERR {e}"
        f.write(f"{t}: {n}\n")
c.close()