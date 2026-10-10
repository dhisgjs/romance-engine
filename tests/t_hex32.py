# -*- coding: utf-8 -*-
"""扫内存中所有 32位hex 字符串（数据库 passphrase 形态），
将其 hex 解码为 16 字节（或取前32字符）当图片 key 尝试。

也试：32位hex字符串的前16字符 ASCII 作为 key（32字节 key 取前16）。
"""
import ctypes
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import memscan
from backend.core.media import detect_format
from Crypto.Cipher import AES

V2 = b"\x07\x08V2\x08\x07"
MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")


def is_img(d):
    return any(d.startswith(m) for m in MAGICS) or (d[:4] == b"RIFF" and d[8:12] == b"WEBP")


# 收集 189 个原图密文块（去重）
attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"
blocks, seen = [], set()
for r, _d, fl in os.walk(attach):
    for f in fl:
        if not f.endswith(".dat") or f.endswith("_t.dat"):
            continue
        p = os.path.join(r, f)
        try:
            with open(p, "rb") as fh:
                h = fh.read(31)
        except OSError:
            continue
        if h[:6] != V2:
            continue
        blk = h[15:31]
        if blk not in seen:
            seen.add(blk)
            blocks.append(blk)
print(f"验证样本: {len(blocks)} 块")
SAMPLE = blocks[:12]  # 抽12个做快速验证


def try_key(kb):
    try:
        c = AES.new(kb, AES.MODE_ECB)
    except Exception:
        return 0
    return sum(1 for ct in SAMPLE if is_img(c.decrypt(ct)))


HEX_PAT = re.compile(rb"(?<![0-9a-fA-F])([0-9a-fA-F]{32})(?![0-9a-fA-F])")
pids = memscan.find_wechat_pids()
out = []
tested = set()
t0 = time.time()
for pid in pids:
    h = memscan.kernel32.OpenProcess(
        memscan.PROCESS_VM_READ | memscan.PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        continue
    try:
        for base, size in memscan._iter_readable_regions(h):
            if size > 300 * 1024 * 1024:
                continue
            off = 0
            while off < size:
                rl = min(memscan.CHUNK, size - off)
                buf = ctypes.create_string_buffer(rl + memscan.OVERLAP)
                n = ctypes.c_size_t(0)
                if memscan.kernel32.ReadProcessMemory(
                        ctypes.c_void_p(h), ctypes.c_uint64(base + off), buf,
                        ctypes.c_size_t(rl + memscan.OVERLAP), ctypes.byref(n)) and n.value > 0:
                    data = buf.raw[:n.value]
                    for m in HEX_PAT.finditer(data):
                        s = m.group(1)
                        if s in tested:
                            continue
                        tested.add(s)
                        try:
                            kb = bytes.fromhex(s.decode())
                        except ValueError:
                            continue
                        hit = try_key(kb)
                        if hit >= 3:
                            out.append(f"HIT hex32 pid={pid} {s.decode()} -> {kb.hex()} 命中{hit}/{len(SAMPLE)}")
                if rl < memscan.CHUNK:
                    break
                off += rl - memscan.OVERLAP
    finally:
        memscan.kernel32.CloseHandle(ctypes.c_void_p(h))
    print(f"pid {pid}: 累计测试 {len(tested)} 个hex32, 耗时 {time.time()-t0:.1f}s")

text = f"测试 {len(tested)} 个 hex32 候选\n" + ("\n".join(out) if out else "无命中")
with open("out_tmp32.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text[:3000])