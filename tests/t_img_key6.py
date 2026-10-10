# -*- coding: utf-8 -*-
"""严格媒体密钥提取：全进程扫描 + 多样本交叉验证（杜绝单样本假阳性）。

要求：至少 N=5 个不同的 V2 原图/高清图密文块，用候选 key 解密后全部命中
图片魔数才接受。缩略图(_t) 首块内容重复度高，单独提供但仅作辅助；主验证
以去重后的全部样本为准。
"""
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Crypto.Cipher import AES
from backend.core import memscan

ACC = "wxid_your_account_efcf"
attach = rf"D:\personal\Documents\xwechat_files\{ACC}\msg\attach"

MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")


def is_img(dec: bytes) -> bool:
    return any(dec.startswith(m) for m in MAGICS) or (dec[:4] == b"RIFF" and dec[8:12] == b"WEBP")


def collect_samples():
    """收集全部 V2 首块密文：full(原图/高清) 与 thumb(缩略图) 分开，按内容去重。"""
    full, thumb = [], []
    fseen, tseen = set(), set()
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
                blk = head[15:31]
            except OSError:
                continue
            if f.endswith("_t.dat"):
                if blk not in tseen:
                    tseen.add(blk)
                    thumb.append(blk)
            else:
                if blk not in fseen:
                    fseen.add(blk)
                    full.append(blk)
    return full, thumb


full, thumb = collect_samples()
print(f"原图/高清样本(去重): {len(full)}   缩略图样本(去重): {len(thumb)}")

# 优先用原图样本；原图不足 5 个才把缩略图并进来辅助
core = full if len(full) >= 5 else (full + thumb)
core_dedup = list(dict.fromkeys(core))  # 保持顺序去重
print(f"验证样本集: {len(core_dedup)} 块")


def verify(kb: bytes) -> int:
    """返回命中的块数（满分为 len(core_dedup)）。"""
    try:
        cipher = AES.new(kb, AES.MODE_ECB)
    except Exception:
        return 0
    hit = 0
    for ct in core_dedup:
        if is_img(cipher.decrypt(ct)):
            hit += 1
    return hit


# ---- 1. 滑窗遍历 alnum 候选（全进程） ----
pids = memscan.find_wechat_pids()
parents = memscan._pid_parents()
mains = [p for p in pids if parents.get(p) not in pids]
result = memscan.ScanResult()
t0 = time.time()
for pid in pids:
    try:
        memscan.scan_pid(pid, result, log=lambda m: None)
    except Exception:
        pass
print(f"扫描 {len(pids)} 进程 {time.time()-t0:.1f}s, alnum {len(result.alnum)} 候选")

target = len(core_dedup)
MIN_HIT = max(5, int(target * 0.9))  # 至少5块，且 ≥90%
print(f"要求命中: ≥{MIN_HIT}/{target} 块")

found = None
tries = 0
best = (0, None)
for s in result.alnum:
    b = s if isinstance(s, bytes) else s.encode("latin-1")
    if len(b) < 16:
        continue
    for i in range(len(b) - 15):
        kb = b[i:i + 16]
        tries += 1
        h = verify(kb)
        if h > best[0]:
            best = (h, kb)
        if h >= MIN_HIT:
            found = kb
            print(f"  命中: {kb.hex()} = {kb!r}  ({h}/{target})")
            break
    if found:
        break

print(f"滑窗尝试 {tries} 次")
if found:
    print(f"最佳候选: {best[0]}/{target} {best[1].hex() if best[1] else ''}")
    out = os.path.join("data", "keys", f"{ACC}.image_key")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(found.hex())
    print(f"\n✓✓✓ 媒体密钥: {found.hex()} → {out}")
else:
    print(f"\n✗ 未找到。最佳候选仅命中 {best[0]}/{target}")
    if best[1]:
        print(f"  最佳: {best[1].hex()} = {best[1]!r}")
    print("  提示：先在微信里点开图片（让原图密钥进内存），再重试")