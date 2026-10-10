# -*- coding: utf-8 -*-
import os
import sqlite3

base = r"data\decrypted\wxid_your_account_efcf\message"
for fn in os.listdir(base):
    p = os.path.join(base, fn)
    try:
        sz = os.path.getsize(p)
    except OSError:
        continue
    uri = "file:" + p.replace("\\", "/")
    out = [f"== {fn} size={sz}"]
    for suffix in ("?mode=ro&immutable=1", "?mode=ro"):
        try:
            c = sqlite3.connect(uri + suffix, uri=True)
            tabs = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            n = 0
            for (t,) in tabs:
                if t.startswith("Msg_"):
                    try:
                        n += c.execute('SELECT count(*) FROM "' + t + '"').fetchone()[0]
                    except Exception:
                        pass
            out.append(f"  [{suffix}] tables={len(tabs)} msg_rows={n}")
            c.close()
        except Exception as e:
            out.append(f"  [{suffix}] ERR {e}")
    print("\n".join(out))