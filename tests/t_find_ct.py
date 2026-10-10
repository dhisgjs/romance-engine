# -*- coding: utf-8 -*-
"""在微信进程内存中定位磁盘 AES 密文首块的来源，观察其周边结构。"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import memscan

# 原图 AES 区第一块密文（所有原图都一样）
FULL_CT = bytes.fromhex("9513939620f7e2596a1f965303b7745e")
# 缩略图 AES 区第一块密文（所有缩略图都一样）
THUMB_CT = bytes.fromhex("dbba9010b17514f1d071bda624f06b99")


def find_all(h, needle, limit=5):
    hits = []
    for base, size in memscan._iter_readable_regions(h):
        off = 0
        while off < size:
            rl = min(memscan.CHUNK, size - off)
            buf = ctypes.create_string_buffer(rl + memscan.OVERLAP)
            n = ctypes.c_size_t(0)
            if memscan.kernel32.ReadProcessMemory(
                    ctypes.c_void_p(h), ctypes.c_uint64(base + off), buf,
                    ctypes.c_size_t(rl + memscan.OVERLAP), ctypes.byref(n)) and n.value > 0:
                data = buf.raw[:n.value]
                p = data.find(needle)
                while p >= 0 and len(hits) < limit:
                    hits.append((base + off + p, data[max(0, p-48):p+64]))
                    p = data.find(needle, p + 1)
                if len(hits) >= limit:
                    return hits
            if rl < memscan.CHUNK:
                break
            off += rl - memscan.OVERLAP
    return hits


out = []
pids = memscan.find_wechat_pids()
for pid in pids:
    h = memscan.kernel32.OpenProcess(
        memscan.PROCESS_VM_READ | memscan.PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        continue
    try:
        for name, needle in (("原图密文块", FULL_CT), ("缩略图密文块", THUMB_CT)):
            hits = find_all(h, needle)
            if hits:
                out.append(f"pid {pid} 命中 {name}: {len(hits)}处")
                for addr, ctx in hits[:3]:
                    out.append(f"   @ {hex(addr)}")
                    out.append(f"   前48: {ctx[:48].hex()}")
                    out.append(f"   目标+后64: {ctx[48:].hex()}")
                    # 前48 是否有可读ASCII
                    txt = "".join(chr(c) if 32 <= c < 127 else "." for c in ctx[:48])
                    out.append(f"   前48 ASCII: {txt}")
            else:
                out.append(f"pid {pid} {name}: 未找到")
    finally:
        memscan.kernel32.CloseHandle(ctypes.c_void_p(h))
    if len(out) > 40:
        break

with open("out_tmp12.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out[:40]))