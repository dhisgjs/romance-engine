# -*- coding: utf-8 -*-
"""在解密后的数据库中查找图片 aeskey 线索：遍历所有库的所有表/字段名+样例值。"""
import os
import re
import sqlite3

root = os.path.join("data", "decrypted", "wxid_your_account_efcf")
out = []

# 1) 全局搜：所有 sqlite_master 里名字含 key/aes/crypt/media/image 的表和字段
pats = re.compile(r"(key|aes|crypt|media|image|img)", re.I)
for dirpath, _dirs, files in os.walk(root):
    for fn in files:
        if not fn.endswith(".db"):
            continue
        p = os.path.join(dirpath, fn)
        try:
            c = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
            tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for t in tabs:
                cols = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]
                hit_cols = [x for x in cols if pats.search(x)]
                hit_tab = bool(pats.search(t))
                if hit_cols or hit_tab:
                    out.append(f"{os.path.relpath(p, root).replace(chr(92),'/')} :: {t} :: cols={hit_cols}")
                    # 取一行看值
                    if hit_cols:
                        try:
                            sel = ", ".join(f'"{x}"' for x in hit_cols[:6])
                            for row in c.execute(f'SELECT {sel} FROM "{t}" LIMIT 3'):
                                out.append(f"      sample: {row}")
                        except Exception as e:
                            out.append(f"      (err {e})")
            c.close()
        except Exception as e:
            out.append(f"{os.path.relpath(p, root)}: 打开失败 {e}")

with open("out_tmp13.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out[:80]))