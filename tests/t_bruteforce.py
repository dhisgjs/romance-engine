# -*- coding: utf-8 -*-
"""暴力扫内存：任意 16 字节序列作为 key，验证能否解出图片魔数。
优化：先用「快速过滤」——只对可打印ASCII 或高熵候选做完整AES验证。
第一阶段：找出所有16字节窗口，若解密结果首4字节命中图片魔数则报出。
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import memscan
from Crypto.Cipher import AES

# 用缩略图首块（样本少但同样固定）：7 个去重块
THUMB_CT = bytes.fromhex("dbba9010b17514f1d071bda624f06b99")
# 原图首块
FULL_CT = bytes.fromhex("9513939620f7e2596a1f965303b7745e")
MAGIC_PREFIXES = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")

ct = THUMB_CT
pids = memscan.find_wechat_pids()
print(f"进程 {pids}")

out = []
t0 = time.time()
total_checked = 0
for pid in pids:
    h = memscan.kernel32.OpenProcess(
        memscan.PROCESS_VM_READ | memscan.PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        continue
    try:
        for base, size in memscan._iter_readable_regions(h):
            if size > 200 * 1024 * 1024:
                continue
            off = 0
            while off < size:
                rl = min(4 * 1024 * 1024, size - off)
                buf = ctypes.create_string_buffer(rl)
                n = ctypes.c_size_t(0)
                if memscan.kernel32.ReadProcessMemory(
                        ctypes.c_void_p(h), ctypes.c_uint64(base + off), buf,
                        ctypes.c_size_t(rl), ctypes.byref(n)) and n.value > 32:
                    data = buf.raw[:n.value]
                    # 滑动窗口：每个偏移作为 16B key
                    for i in range(len(data) - 16):
                        kb = data[i:i + 16]
                        # 快速剪枝：key 不能全0/全FF
                        if kb.count(0) > 12 or kb.count(0xFF) > 12:
                            continue
                        try:
                            dec = AES.new(kb, AES.MODE_ECB).decrypt(ct)
                        except Exception:
                            continue
                        total_checked += 1
                        if dec.startswith(MAGIC_PREFIXES):
                            out.append(f"HIT pid={pid} addr={hex(base+off+i)} key={kb.hex()} key_repr={kb!r} dec={dec[:12].hex()}")
                            if len(out) >= 30:
                                break
                    if len(out) >= 30:
                        break
                if rl < 4 * 1024 * 1024:
                    break
                off += rl
            if len(out) >= 30:
                break
    finally:
        memscan.kernel32.CloseHandle(ctypes.c_void_p(h))
    if len(out) >= 30:
        break
    print(f"pid {pid} 完成，已检查 {total_checked} 个key, 耗时{time.time()-t0:.1f}s")

text = f"检查 {total_checked} 个候选key, 命中 {len(out)}\n" + "\n".join(out)
with open("out_tmp28.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text[:3000])