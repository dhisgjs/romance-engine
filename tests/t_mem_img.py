# -*- coding: utf-8 -*-
"""在微信进程内存中搜索 JPEG/PNG/WEBP 明文图片（用户点开过的图会被缓存）。

目的有二：
  1. 确认图片真实格式（进而确认真实 AES 明文首块内容）
  2. 通过同一 key 加密同一明文 => 密文相同，反推 AES 区首块对应的明文
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import memscan

# 在内存块中查找图片魔数
MAGICS = {b"\xff\xd8\xff\xe0": "jpeg-jfif", b"\xff\xd8\xff\xe1": "jpeg-exif", b"\xff\xd8\xff\xdb": "jpeg",
          b"\x89PNG\r\n\x1a\n": "png", b"GIF89a": "gif89", b"GIF87a": "gif87"}


def scan_images(pid: int, limit: int = 20):
    h = memscan.kernel32.OpenProcess(
        memscan.PROCESS_VM_READ | memscan.PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return []
    hits = []
    try:
        for base, size in memscan._iter_readable_regions(h):
            off = 0
            while off < size:
                rl = min(memscan.CHUNK, size - off)
                buf = ctypes.create_string_buffer(rl + memscan.OVERLAP)
                n = ctypes.c_size_t(0)
                if memscan.kernel32.ReadProcessMemory(
                        ctypes.c_void_p(h), ctypes.c_uint64(base + off), buf,
                        ctypes.c_size_t(rl + memscan.OVERLAP), ctypes.byref(n)) and n.value > 32:
                    data = buf.raw[:n.value]
                    for magic, name in MAGICS.items():
                        pos = data.find(magic)
                        if pos >= 0:
                            seg = data[pos:pos + 32]
                            hits.append((name, hex(base + off + pos), seg.hex(),
                                         os.path.getsize("/proc/self") if False else 0))
                            if len(hits) >= limit:
                                return hits
                if rl < memscan.CHUNK:
                    break
                off += rl - memscan.OVERLAP
    finally:
        memscan.kernel32.CloseHandle(ctypes.c_void_p(h))
    return hits


out = []
pids = memscan.find_wechat_pids()
print(f"进程: {pids}")
for pid in pids:
    try:
        hits = scan_images(pid)
    except Exception as e:
        out.append(f"pid {pid} 异常: {e}")
        continue
    if hits:
        out.append(f"pid {pid}: 找到 {len(hits)} 处明文图片")
        for name, addr, hx, _ in hits:
            out.append(f"    {name} @ {addr}: {hx}")
    else:
        out.append(f"pid {pid}: 无")

with open("out_tmp11.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("\n".join(out))