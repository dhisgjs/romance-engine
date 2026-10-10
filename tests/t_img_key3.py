# -*- coding: utf-8 -*-
"""提取媒体密钥：用本地 V2 图片（小宝聊天的）做已知明文攻击。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Crypto.Cipher import AES
from backend.core import memscan

ACC = "wxid_your_account_efcf"
attach = rf"D:\personal\Documents\xwechat_files\{ACC}\msg\attach"


def sample_blocks(limit=10):
    blocks = []
    for root, _d, files in os.walk(attach):
        for f in files:
            if not f.endswith(".dat"):
                continue
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fh:
                    head = fh.read(31)
                if head[:6] != b"\x07\x08V2\x08\x07":
                    continue
                blocks.append(head[15:31])
            except OSError:
                continue
            if len(blocks) >= limit:
                return blocks
    return blocks


blocks = sample_blocks()
print(f"V2 图片样本: {len(blocks)} 块（本地文件齐全）")
MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")


def try_key(kb):
    try:
        cipher = AES.new(kb, AES.MODE_ECB)
    except Exception:
        return False
    for ct in blocks:
        dec = cipher.decrypt(ct)
        if not any(dec.startswith(m) for m in MAGICS) and not (dec[:4] == b"RIFF" and dec[8:12] == b"WEBP"):
            return False
    return True


# 扫主进程
pids = memscan.find_wechat_pids()
parents = memscan._pid_parents()
mains = [p for p in pids if parents.get(p) not in pids]
result = memscan.ScanResult()
t0 = time.time()
for pid in mains:
    memscan.scan_pid(pid, result, log=lambda m: None)
print(f"扫描主进程 {time.time()-t0:.1f}s, alnum 候选 {len(result.alnum)}")

# 试 alnum + hex 候选
found = None
for s in result.alnum:
    b = s if isinstance(s, bytes) else s.encode("latin-1")
    for kb in {b[:16], b[-16:]}:
        if len(kb) == 16 and try_key(kb):
            found = kb
            break
    if found:
        break

if not found:
    # 试 hex 候选
    cands = set()
    for s in result.candidates:
        s2 = s.strip("x'").strip("'")
        if len(s2) >= 64:
            cands.add(s2[:64][:32])
            cands.add(s2[-64:][32:])
    for s in cands:
        try:
            kb = bytes.fromhex(s[:32])[:16]
            if len(kb) == 16 and try_key(kb):
                found = kb
                break
        except Exception:
            pass

if found:
    out = os.path.join("data", "keys", f"{ACC}.image_key")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(found.hex())
    print(f"✓✓✓ 提取到媒体密钥: {found.hex()} 已保存")
else:
    print("✗ 未找到（微信内存里没有媒体密钥）")
    print("  说明：需要在微信里打开 1-2 张图片让密钥缓存进内存，然后我再提取")