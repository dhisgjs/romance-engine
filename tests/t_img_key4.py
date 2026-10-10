# -*- coding: utf-8 -*-
"""诊断媒体密钥提取：详细打印每一步，找失败原因。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Crypto.Cipher import AES
from backend.core import memscan, media as media_mod

ACC = "wxid_your_account_efcf"
attach = rf"D:\personal\Documents\xwechat_files\{ACC}\msg\attach"

# 1. 样本文件：V2 原图 + 缩略图（用 _t 兜底）
blocks_orig = media_mod.find_sample_blocks(attach, limit=10)
blocks_thumb = []
for root, _d, files in os.walk(attach):
    for f in files:
        if f.endswith("_t.dat"):
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fh:
                    head = fh.read(31)
                if head[:6] == b"\x07\x08V2\x08\x07":
                    blocks_thumb.append(head[15:31])
            except OSError:
                pass
        if len(blocks_thumb) >= 10:
            break
    if len(blocks_thumb) >= 10:
        break
print(f"V2 原图样本 {len(blocks_orig)} 块, 缩略图样本 {len(blocks_thumb)} 块")

# 合并去重
samples = list({b for b in blocks_orig + blocks_thumb})
print(f"去重后样本 {len(samples)} 块")
for b in samples[:5]:
    print("  sample:", b.hex()[:24])

MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")


def try_key(kb):
    try:
        cipher = AES.new(kb, AES.MODE_ECB)
    except Exception:
        return False
    for ct in samples:
        dec = cipher.decrypt(ct)
        if not any(dec.startswith(m) for m in MAGICS) and not (dec[:4] == b"RIFF" and dec[8:12] == b"WEBP"):
            return False
    return True


# 2. 扫描所有微信进程（不只主进程），收集全部候选类型
pids = memscan.find_wechat_pids()
parents = memscan._pid_parents()
mains = [p for p in pids if parents.get(p) not in pids]
print(f"\n进程: {len(pids)} 个, 主进程 {mains}")

result = memscan.ScanResult()
t0 = time.time()
for pid in pids:  # 扫全部进程（多花时间但更全）
    memscan.scan_pid(pid, result, log=lambda m: None)
print(f"扫描全部进程 {time.time()-t0:.1f}s")
print(f"alnum候选 {len(result.alnum)}, candidates {len(result.candidates)}, "
      f"bare_keys {len(result.bare_keys)}, passphrase {len(result.pass_candidates)}")

# 3. 已知明文攻击：alnum（16字节）→ hex 候选 → 32字节 alnum
found = None
print("\n阶段1: alnum 16字节…")
for s in result.alnum:
    b = s if isinstance(s, bytes) else s.encode("latin-1")
    for kb in {b[:16], b[-16:]}:
        if len(kb) == 16 and try_key(kb):
            found = kb
            break
    if found:
        break

if not found:
    print("阶段2: hex 候选 16字节…")
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

if not found:
    print("阶段3: alnum 32字节（AES-256）…")
    for s in result.alnum:
        b = s if isinstance(s, bytes) else s.encode("latin-1")
        if len(b) == 32 and try_key(b):
            found = b
            break

if found:
    out = os.path.join("data", "keys", f"{ACC}.image_key")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(found.hex())
    print(f"\n✓✓✓ 提取到媒体密钥: {found.hex()}")
else:
    # 4. 打印一些候选样本（判断密钥形态）
    print("\n✗ 未找到。alnum 候选样本:")
    for s in list(result.alnum)[:8]:
        b = s if isinstance(s, bytes) else s.encode("latin-1")
        print(f"  {b[:32].hex()} = {b[:32]!r}")