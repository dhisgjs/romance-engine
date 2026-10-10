# -*- coding: utf-8 -*-
"""端到端自测：内存扫描 -> 密钥匹配 -> 解密 -> 联系人/消息 -> 导出。
只打印统计数据与少量技术信息用于验证，不输出聊天内容。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.core import decrypt, exporter, memscan
from backend.core.models import Store

DECRYPTED = os.path.join(ROOT, "data", "decrypted")
KEYS = os.path.join(ROOT, "data", "keys")


def main():
    t0 = time.time()
    pids = memscan.find_wechat_pids()
    print(f"[1] 微信相关进程: {len(pids)} 个")
    dirs = memscan.find_data_dirs()
    print(f"[2] 数据目录: {dirs}")
    if not dirs:
        sys.exit("未找到数据目录")
    data_dir = dirs[0]
    accounts = memscan.list_accounts(data_dir)
    print(f"[3] 账号: {accounts}")

    print("[4] 扫描进程内存…")
    result = memscan.scan_memory(
        log=lambda m: print("   " + m),
        progress=lambda c, t: None,
    )
    print(f"[5] 扫描完成: x'..'候选 {len(result.candidates)}, 纯key {len(result.bare_keys)}, "
          f"passphrase候选 {len(result.pass_candidates)}, 耗时 {time.time()-t0:.1f}s")

    for acc in accounts:
        storage = os.path.join(data_dir, acc, "db_storage")
        matched = memscan.match_keys(storage, result, log=lambda m: print("   " + m))
        if not matched:
            print(f"--- {acc}: 未匹配到密钥（可能非当前登录账号）---")
            continue
        print(f"--- {acc}: {len(matched)} 个库已配对，开始解密 ---")
        ok = 0
        for db, k in sorted(matched.items()):
            rel = os.path.relpath(db, storage)
            out = os.path.join(DECRYPTED, acc, rel)
            r = decrypt.decrypt_database(db, out, k[:64])
            ok += r["ok"]
            if not r["ok"]:
                print(f"    FAIL {rel}: {r['error']}")
        print(f"    解密成功 {ok}/{len(matched)}")

        store = Store(DECRYPTED, acc)
        contacts = store.contacts()
        print(f"    联系人 {len(contacts)} 个")
        talkers = store.known_talkers()
        print(f"    有消息表的聊天对象 {len(talkers)} 个")
        ranked = sorted(talkers, key=lambda t: -store.message_count(t))[:5]
        for t in ranked:
            print(f"      {t[:12]}***  {store.message_count(t)} 条")

        if ranked:
            target = ranked[0]
            t2 = time.time()
            msgs = store.messages(target)
            print(f"    导出验证对象 {target[:12]}***: {len(msgs)} 条, 读取 {time.time()-t2:.1f}s")
            types = {}
            for m in msgs:
                types[m["type"]] = types.get(m["type"], 0) + 1
            print(f"    类型分布: {dict(sorted(types.items(), key=lambda x: -x[1]))}")
            self_n = sum(1 for m in msgs if m["is_self"])
            print(f"    自发消息 {self_n} 条, 对方 {len(msgs)-self_n} 条")
            out_dir = os.path.join(ROOT, "data", "exports", "_test")
            r = exporter.export_contact(store, target, "html", out_dir)
            print(f"    HTML 导出: {r['file']} ({r['bytes']//1024}KB, {r['count']} 条)")
            r2 = exporter.export_contact(store, target, "csv", out_dir)
            print(f"    CSV  导出: {r2['file']} ({r2['bytes']//1024}KB)")
    print(f"\n全部完成，总耗时 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
