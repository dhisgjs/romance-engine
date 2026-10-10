# -*- coding: utf-8 -*-
"""扫内存中所有 16 字节「可打印ASCII」窗口作为候选 key，
用原图+缩略图两个固定密文块交叉验证（大幅剪枝）。
"""
import ctypes
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import memscan
from Crypto.Cipher import AES

FULL_CT = bytes.fromhex("9513939620f7e2596a1f965303b7745e")
THUMB_CT = bytes.fromhex("dbba9010b17514f1d071bda624f06b99")
# 另一个原图块（不同明文，用于交叉验证）
FULL_CT2 = bytes.fromhex("368c7618f4ffea3712992e642610fddd")
FULL_CT3 = bytes.fromhex("3c1bd1e537e1c70b41b7ff5c0b082735")
MAGICS = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"wxgf")


def is_img(d):
    return any(d.startswith(m) for m in MAGICS) or (d[:4] == b"RIFF" and d[8:12] == b"WEBP")


PRINT = bytes(range(0x20, 0x7F))  # 可打印ASCII
PSET = set(PRINT)


def check(kb):
    """key 解密 FULL_CT 与 THUMB_CT，是否都是图片。"""
    try:
        c = AES.new(kb, AES.MODE_ECB)
        a = is_img(c.decrypt(FULL_CT))
        b = is_img(c.decrypt(THUMB_CT))
        if a and b:
            return True, True
        if a:
            # 只命中原图，再交叉验证第二个原图块
            return False, is_img(c.decrypt(FULL_CT2)) or is_img(c.decrypt(FULL_CT3))
        return False, False
    except Exception:
        return False, False


pids = memscan.find_wechat_pids()
out = []
t0 = time.time()
checked = 0
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
                rl = min(4 * 1024 * 1024, size - off)
                buf = ctypes.create_string_buffer(rl)
                n = ctypes.c_size_t(0)
                if memscan.kernel32.ReadProcessMemory(
                        ctypes.c_void_p(h), ctypes.c_uint64(base + off), buf,
                        ctypes.c_size_t(rl), ctypes.byref(n)) and n.value > 40:
                    data = buf.raw[:n.value]
                    i = 0
                    L = len(data) - 16
                    while i <= L:
                        # 找连续16个可打印ASCII
                        b = data[i]
                        if b in PSET:
                            j = i
                            while j <= L and data[j] in PSET:
                                j += 1
                            runlen = j - i
                            if runlen >= 16:
                                for s in range(i, j - 15):
                                    kb = data[s:s + 16]
                                    checked += 1
                                    ok_full, ok_thumb = check(kb)
                                    if ok_full or ok_thumb:
                                        kind = "原图" if ok_full else "缩略图"
                                        out.append(
                                            f"HIT[{kind}] pid={pid} addr={hex(base+off+s)} "
                                            f"key={kb.hex()} key_ascii={kb!r}")
                                        if len(out) >= 40:
                                            break
                                if len(out) >= 40:
                                    break
                            i = j
                        else:
                            i += 1
                    if len(out) >= 40:
                        break
                if rl < 4 * 1024 * 1024:
                    break
                off += rl
            if len(out) >= 40:
                break
    finally:
        memscan.kernel32.CloseHandle(ctypes.c_void_p(h))
    if len(out) >= 40:
        break
    print(f"pid {pid} 完成: 检查 {checked}, 耗时 {time.time()-t0:.1f}s")

text = f"检查 {checked} 个可打印候选, 命中 {len(out)}\n" + "\n".join(out)
with open("out_tmp29.txt", "w", encoding="utf-8") as f:
    f.write(text)
print(text[:4000])