# -*- coding: utf-8 -*-
"""在指定文件里滑动任意 16 字节窗口，用已知 V2 密文块严格验证是否为图片密钥。

严格标准：候选密钥必须解开 >=5 个不同密文块，且命中率 >=90%，
且解出的明文以已知图片魔数开头（ffd8ff / 89504e / GIF8 / BM / RIFF / ftyp）。
"""
import os
import sys

from Crypto.Cipher import AES

V2 = b"\x07\x08V2\x08\x07"
attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
acct = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf"

MAGICS = (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb",
          b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM", b"RIFF", b"II*\x00", b"MM\x00*")


def collect_blocks(limit=60):
    """收集不同文件的 aes_zone 首块作为密文样本。"""
    blocks = []
    seen = set()
    for r, _d, fl in os.walk(attach):
        for f in fl:
            if not f.endswith(".dat"):
                continue
            try:
                with open(os.path.join(r, f), "rb") as fh:
                    head = fh.read(64)
            except OSError:
                continue
            if len(head) < 32 or head[:6] != V2:
                continue
            a = int.from_bytes(head[6:10], "little")
            z = head[15:31]
            if a < 16 or len(z) < 16 or z in seen:
                continue
            seen.add(z)
            blocks.append(z)
            if len(blocks) >= limit:
                return blocks
    return blocks


def scan_file(path, blocks):
    """滑动 16 字节窗口，返回严格命中的候选。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return []
    n = len(data)
    hits = []
    need = max(5, int(len(blocks) * 0.9))
    for off in range(0, n - 15):
        key = data[off:off + 16]
        if key in hits_keys:
            continue
        ok = 0
        good = False
        for ct in blocks:
            pt = AES.new(key, AES.MODE_ECB).decrypt(ct)
            if pt.startswith(MAGICS) or pt[4:8] == b"ftyp":
                ok += 1
                good = True
        if good and ok >= need:
            hits.append((off, key, ok))
            hits_keys.add(key)
    return hits


if __name__ == "__main__":
    blocks = collect_blocks()
    print(f"密文样本 {len(blocks)} 块, 首块 {blocks[0].hex()}")
    targets = []
    for rel in [r"config\newclientconfig\config",
                r"config\login_configv2",
                r"config\file_config_2026v2",
                r"config\file_config_2026",
                r"config\xlab\config",
                r"config\login_config",
                r"config\rs_config",
                r"config\chatbot_config"]:
        p = os.path.join(acct, rel)
        if os.path.isfile(p):
            targets.append(p)
    for p in sys.argv[1:]:
        if os.path.isfile(p):
            targets.append(p)

    total_hits = 0
    lines = []
    for p in targets:
        hits_keys = set()
        hits = scan_file(p, blocks)
        total_hits += len(hits)
        tag = "命中!" if hits else "无"
        lines.append(f"{tag} {p} size={os.path.getsize(p)} -> {len(hits)}")
        for off, key, ok in hits:
            lines.append(f"    off={off} key={key.hex()} {ok}/{len(blocks)}")
        print(lines[-1], flush=True)

    lines.insert(0, f"扫描 {len(targets)} 个文件, 严格命中合计 {total_hits}")
    with open("out_tmp35.txt", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"\n合计严格命中 {total_hits}")