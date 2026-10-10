# -*- coding: utf-8 -*-
"""抓取内存中的完整 JPEG 明文，与磁盘 .dat 做配对分析。"""
import ctypes
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import memscan

PID = 11444
h = memscan.kernel32.OpenProcess(
    memscan.PROCESS_VM_READ | memscan.PROCESS_QUERY_INFORMATION, False, PID)
if not h:
    print("无法打开进程")
    sys.exit(1)

images = []
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
                p = 0
                while True:
                    i = data.find(b"\xff\xd8\xff\xe0", p)
                    if i < 0:
                        break
                    # 找结束标记 FFD9
                    j = data.find(b"\xff\xd9", i)
                    if j > 0:
                        blob = data[i:j + 2]
                        if len(blob) > 5000:
                            images.append((base + off + i, blob))
                    p = i + 4
            if rl < memscan.CHUNK:
                break
            off += rl - memscan.OVERLAP
finally:
    memscan.kernel32.CloseHandle(ctypes.c_void_p(h))

print(f"抓到 {len(images)} 张内存JPEG")
out = []
big = sorted(images, key=lambda t: -len(t[1]))[:8]
for addr, blob in big:
    # 解析 JPEG 尺寸
    w = hh = 0
    i = 2
    while i < len(blob) - 9:
        if blob[i] != 0xFF:
            i += 1
            continue
        marker = blob[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            hh = struct.unpack(">H", blob[i + 5:i + 7])[0]
            w = struct.unpack(">H", blob[i + 7:i + 9])[0]
            break
        i += 2 + struct.unpack(">H", blob[i + 2:i + 4])[0]
    out.append(f"addr={hex(addr)} size={len(blob)} {w}x{hh} head={blob[:16].hex()}")
    # 保存到磁盘用于比对
    fn = f"tests/memimg_{addr:x}_{w}x{hh}.jpg"
    with open(fn, "wb") as f:
        f.write(blob)

text = "\n".join(out)
with open("tests/out_mem.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text)