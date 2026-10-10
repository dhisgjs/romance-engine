# -*- coding: utf-8 -*-
"""在微信内存中搜索图片 aeskey 的 hex 值 / 混淆形态。

若 CDN aeskey 与本地解密 key 有关，内存中可能同时存在：
  1. aeskey 的原始 hex（在 XML 缓存里）
  2. 本地解密 key（混淆后/原始16字节）
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import memscan

# 一批真实 aeskey（从 XML 拿到的）
AESKEYS = {
    "6e726c726a706b6d7a6f69726a716b6a",  # nrlrjpkmzoirjqj
    "f575d41a7f6908c669f7d3a0d4e19690",
    "7073617670637473776a65736477686e",
    "6b25514e30a173abf18aa12107e84add",
    "272a2fcbdc53790091cdf6f22afbfffe",
    "afa87d820634aba52830026e527dc257",
}
HEXS = {bytes.fromhex(k) for k in AESKEYS}


def find(pid, needles, limit=6):
    """在进程内存中搜索 needles（bytes）。返回匹配。"""
    hits = []
    h = memscan.kernel32.OpenProcess(
        memscan.PROCESS_VM_READ | memscan.PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        return hits
    try:
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
                    for nd in needles:
                        p = data.find(nd)
                        while p >= 0 and len(hits) < limit:
                            ctx = data[max(0, p - 24):p + 64]
                            hits.append((hex(base + off + p), nd.hex(), ctx[:48].hex()))
                            p = data.find(nd, p + 1)
                    if len(hits) >= limit:
                        return hits
                if rl < memscan.CHUNK:
                    break
                off += rl - memscan.OVERLAP
    finally:
        memscan.kernel32.CloseHandle(ctypes.c_void_p(h))
    return hits


pids = memscan.find_wechat_pids()
out = []
for pid in pids:
    for label, needles in (
        ("hex-ascii", [k.encode() for k in AESKEYS]),
        ("hex-bytes", [b for b in HEXS]),
    ):
        hits = find(pid, needles)
        if hits:
            out.append(f"pid {pid} {label}: {len(hits)} 命中")
            for addr, nd, ctx in hits[:4]:
                out.append(f"   @{addr} needle={nd} ctx={ctx}")
    print(f"pid {pid} done")

text = "\n".join(out) if out else "所有进程都未找到 aeskey 的 hex 或 bytes 形态"
with open("out_tmp30.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text[:3000])