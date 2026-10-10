# -*- coding: utf-8 -*-
import os

attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
targets = ("1f281d8edb5d522b6b0e7695726dbc13.dat",
           "1f281d8edb5d522b6b0e7695726dbc13_h.dat",
           "70ef62a5a4685885b186ef3e7048c763.dat",
           "0062a7c817749236aac7c8dbc524a037.dat",
           "73d5b8d0b041426b619d6c0e263444b2.dat",
           "7962f42164e1ebf9a75764fd75db5859.dat")
out = []
for target in targets:
    for r, _d, fl in os.walk(attach):
        for f in fl:
            if f == target:
                with open(os.path.join(r, f), "rb") as fh:
                    d = fh.read(31)
                out.append(f"{target}: ct0={d[15:31].hex()}")
with open("out_ct.txt", "w", encoding="utf-8") as fh:
    fh.write("\n".join(out))
print("\n".join(out))