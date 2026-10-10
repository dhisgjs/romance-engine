# -*- coding: utf-8 -*-
"""改进版媒体密钥提取：滑窗 + 多样本交叉验证。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Crypto.Cipher import AES
from backend.core import memscan

ACC = "wxid_your_account_efcf"
attach = rf"D:\personal\Documents\xwechat_files\{ACC}\msg\attach"

# 收集尽可能多的 V2 样本（原图+缩略图，去重）
samples = []
seen = set()
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
            if blk not in seen:
                seen.add(blk)
                samples.append(blk)
        except OSError:
            pass
        if len(samples) >= 20:
            break
    if len(samples) >= 20:
        break
print(f"V2 样本（去重）: {len(samples)} 块")

MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")


def is_img(dec):
    return any(dec.startswith(m) for m in MAGICS) or (dec[:4] == b"RIFF" and dec[8:12] == b"WEBP")


def verify(kb):
    """用全部样本验证（严格要求全部命中，避免误判）。"""
    try:
        cipher = AES.new(kb, AES.MODE_ECB)
    except Exception:
        return False
    for ct in samples:
        if not is_img(cipher.decrypt(ct)):
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
print(f"扫描 {time.time()-t0:.1f}s, alnum {len(result.alnum)}")

# 滑窗遍历：每个候选串的所有 16 字节窗口
found = None
tries = 0
for s in result.alnum:
    b = s if isinstance(s, bytes) else s.encode("latin-1")
    if len(b) < 16:
        continue
    for i in range(len(b) - 15):
        kb = b[i:i + 16]
        tries += 1
        if verify(kb):
            found = kb
            print(f"  命中 @ 滑窗{i}: {kb.hex()} = {kb!r}")
            break
    if found:
        break

if not found:
    print(f"滑窗未命中（尝试 {tries} 次）")
    # 降级：单样本验证（只要1块命中就信），提高召回
    print("降级：单样本验证…")
    for s in result.alnum:
        b = s if isinstance(s, bytes) else s.encode("latin-1")
        for i in range(len(b) - 15):
            kb = b[i:i + 16]
            try:
                dec = AES.new(kb, AES.MODE_ECB).decrypt(samples[0])
            except Exception:
                continue
            if is_img(dec):
                found = kb
                print(f"  单样本命中: {kb.hex()} = {kb!r}")
                break
        if found:
            break

if found:
    out = os.path.join("data", "keys", f"{ACC}.image_key")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(found.hex())
    print(f"\n✓✓✓ 媒体密钥: {found.hex()} → {out}")
else:
    print("\n✗ 仍未找到")
    print("  可能：密钥不是连续16字节 alnum，或不在 alnum 形态的内存中")