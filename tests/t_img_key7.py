# -*- coding: utf-8 -*-
"""正确提取：原图(含_h) 与 缩略图(_t) 分开，各自独立找密钥。

依据：原图第一块密文固定 95139396...，缩略图第一块固定 dbba9010...，
说明两者密钥不同。混用会互相干扰导致全灭。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from Crypto.Cipher import AES
from backend.core import memscan

ACC = "wxid_your_account_efcf"
attach = rf"D:\personal\Documents\xwechat_files\{ACC}\msg\attach"
MAGICS = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG", "png"), (b"GIF8", "gif"), (b"RIFF", "webp"), (b"BM", "bmp"), (b"wxgf", "hevc"))


def is_img(d: bytes) -> bool:
    return any(d.startswith(m) for m, _ in MAGICS) or (d[:4] == b"RIFF" and d[8:12] == b"WEBP")


def collect(prefix_filter):
    """收集指定类型的 V2 第一块密文（去重）。"""
    blocks = []
    seen = set()
    for root, _d, fl in os.walk(attach):
        for f in fl:
            if not f.endswith(".dat") or not prefix_filter(f):
                continue
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fh:
                    h = fh.read(31)
                if h[:6] != b"\x07\x08V2\x08\x07":
                    continue
                blk = h[15:31]
            except OSError:
                continue
            if blk not in seen:
                seen.add(blk)
                blocks.append(blk)
    return blocks


full_blocks = collect(lambda f: not f.endswith("_t.dat"))   # .dat + _h.dat
thumb_blocks = collect(lambda f: f.endswith("_t.dat"))
print(f"原图块(去重): {len(full_blocks)}   缩略图块(去重): {len(thumb_blocks)}")
print(f"  原图首块: {full_blocks[0].hex() if full_blocks else '-'}")
print(f"  缩略图首块: {thumb_blocks[0].hex() if thumb_blocks else '-'}")

# 先扫全进程拿 alnum 候选
pids = memscan.find_wechat_pids()
parents = memscan._pid_parents()
result = memscan.ScanResult()
t0 = time.time()
for pid in pids:
    try:
        memscan.scan_pid(pid, result, log=lambda m: None)
    except Exception:
        pass
print(f"扫描 {len(pids)} 进程 {time.time()-t0:.1f}s, alnum {len(result.alnum)}")


def find_key(cands, blocks, min_hit):
    """在候选串滑窗中找能解密 >= min_hit 个块的 key。"""
    target = len(blocks)
    best = (0, None)
    for s in cands:
        b = s if isinstance(s, bytes) else s.encode("latin-1")
        if len(b) < 16:
            continue
        for i in range(len(b) - 15):
            kb = b[i:i + 16]
            try:
                cipher = AES.new(kb, AES.MODE_ECB)
            except Exception:
                continue
            h = sum(1 for ct in blocks if is_img(cipher.decrypt(ct)))
            if h > best[0]:
                best = (h, kb)
            if h >= min_hit:
                return kb, h
    return best[1], best[0]


# 先试原图组
min_hit = max(5, len(full_blocks) // 2)
key_f, hf = find_key(result.alnum, full_blocks, min_hit)
print(f"原图组: 要求≥{min_hit}/{len(full_blocks)}，最佳命中 {hf} {key_f.hex() if key_f else ''}")

# 再试缩略图组
min_t = max(5, len(thumb_blocks) // 2)
key_t, ht = find_key(result.alnum, thumb_blocks, min_t)
print(f"缩略图组: 要求≥{min_t}/{len(thumb_blocks)}，最佳命中 {ht} {key_t.hex() if key_t else ''}")

if key_f and hf >= min_hit:
    out = os.path.join("data", "keys", f"{ACC}.image_key")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(key_f.hex())
    print(f"\n✓✓✓ 原图密钥: {key_f.hex()} = {key_f!r} 命中 {hf}/{len(full_blocks)} → {out}")
if key_t and ht >= min_t:
    outt = os.path.join("data", "keys", f"{ACC}.image_key_t")
    with open(outt, "w") as f:
        f.write(key_t.hex())
    print(f"✓✓✓ 缩略图密钥: {key_t.hex()} = {key_t!r} 命中 {ht}/{len(thumb_blocks)} → {outt}")
if not (key_f and hf >= min_hit) and not (key_t and ht >= min_t):
    print("\n✗ 未找到。key 可能不是连续16-32 alnum 形态，或不在已读内存页里")