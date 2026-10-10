# -*- coding: utf-8 -*-
"""尝试从已知 DB key 派生 V2 图片密钥。

派生方式（对每个 DB key 的 hex 字符串与原始 32 字节分别尝试）：
  md5 / sha1[:16] / sha256[:16] / sha256[-16:] / sha512[:16]
  与账号 wxid 拼接后再摘要
  pbkdf2(md5=盐, salt=wxid/0x88/MAGIC, 迭代 1/256/1000/256000)
  与 V1_KEY、0x88、raw16 异或
另加固定已知常量对照。
"""
import hashlib
import os

from Crypto.Cipher import AES

V2 = b"\x07\x08V2\x08\x07"
attach = r"D:\personal\Documents\xwechat_files\wxid_your_account_efcf\msg\attach"

DBKEYS = {
    "contact/contact.db": "b1a90c4009a2d9b246af7c18d687c561ca2326185f9cba0d515ecb623fb48bd8fc0526b5bdf698c3df20824396e1b1f9",
    "emoticon/emoticon.db": "27d7f2d3de19233525479447dd8dea788013f5372a704e1153219ea0400eb8f9548879c2a06afa51999116d90a325433",
    "hardlink/hardlink.db": "132c729af8591f5d813c3e1885849f716ce8c9aea5ef029f12355da9828bc436f32d242dd7673af98a0a613efe32c268",
    "message/biz_message_0.db": "4e250615f0e6e366cb5f2a2ec8ea1c7ab19c4bdc178b7a21267b4527faacb32938bab40144a8149a190cc4d89a5fdd61",
    "message/message_0.db": "ca2d7273e2b80c4004a90b1a3ab960534da2a569a0be8aedba747247a6a44454c08e0dad6ab5c8085f32b14e9c5e13a3",
}
WXID = b"wxid_your_account_efcf"
RAW16 = bytes.fromhex("317b5e3ef5643d5757ddc91fcc25ec82")
V1_KEY = b"cfcd208495d565ef"

MAGICS = (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1", b"\xff\xd8\xff\xdb",
          b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"BM", b"RIFF", b"II*\x00", b"MM\x00*")


def collect_blocks(limit=60):
    blocks, seen = [], set()
    for r, _d, fl in os.walk(attach):
        for f in fl:
            if not f.endswith(".dat"):
                continue
            try:
                with open(os.path.join(r, f), "rb") as fh:
                    head = fh.read(64)
            except OSError:
                continue
            if len(head) < 32 or head[:6] != V2:
                continue
            a = int.from_bytes(head[6:10], "little")
            z = head[15:31]
            if a < 16 or z in seen:
                continue
            seen.add(z)
            blocks.append(z)
            if len(blocks) >= limit:
                return blocks
    return blocks


def derive():
    out = []
    salts = {"wxid": WXID, "xor88": b"\x88" * 16, "magic": V2,
             "v1key": V1_KEY, "raw16": RAW16, "zero": b"\x00" * 16}
    for name, hx in DBKEYS.items():
        kb = bytes.fromhex(hx)
        ks = hx.encode()
        for src_name, src in (("hexstr", ks), ("raw32", kb), ("raw16", kb[:16]), ("raw16b", kb[16:])):
            for hname, hf in (("md5", hashlib.md5), ("sha1", hashlib.sha1),
                              ("sha256", hashlib.sha256), ("sha512", hashlib.sha512)):
                d = hf(src).digest()
                out.append((f"{name}|{src_name}|{hname}|first", d[:16]))
                out.append((f"{name}|{src_name}|{hname}|last", d[-16:]))
            out.append((f"{name}|{src_name}|md5hexstr", hashlib.md5(src).hexdigest()[:16].encode()))
            out.append((f"{name}|{src_name}|sha256hexstr", hashlib.sha256(src).hexdigest()[:16].encode()))
            for sname, s in salts.items():
                for it in (1, 256, 1000, 256000):
                    out.append((f"{name}|{src_name}|pbkdf2_{sname}_{it}",
                                hashlib.pbkdf2_hmac("sha256", src, s, it, 16)))
                out.append((f"{name}|{src_name}|hmac_{sname}",
                            __import__("hmac").new(src, s, hashlib.md5).digest()))
            out.append((f"{name}|{src_name}|xor_raw16", bytes(a ^ b for a, b in zip(src[:16], RAW16))))
            out.append((f"{name}|{src_name}|xor88x16", bytes(a ^ 0x88 for a in src[:16])))
            out.append((f"{name}|{src_name}|rev", src[:16][::-1]))
    for extra in (b"\x07\x08V2\x08\x07" + b"\x00" * 10,
                  bytes.fromhex("9513939620f7e2596a1f965303b7745e"),
                  V1_KEY + V1_KEY,
                  bytes(a ^ b for a, b in zip(V1_KEY * 2, RAW16))):
        out.append(("extra", extra[:16]))
    return out


def test(key, blocks, need):
    ok = 0
    for ct in blocks:
        pt = AES.new(key, AES.MODE_ECB).decrypt(ct)
        if pt.startswith(MAGICS) or pt[4:8] == b"ftyp":
            ok += 1
    return ok


if __name__ == "__main__":
    blocks = collect_blocks()
    print(f"密文样本 {len(blocks)} 块")
    cands = derive()
    print(f"派生候选 {len(cands)} 个")
    need = max(3, int(len(blocks) * 0.5))
    hits = []
    for name, key in cands:
        if len(key) != 16:
            continue
        ok = test(key, blocks, need)
        if ok:
            hits.append((ok, name, key.hex()))
    hits.sort(reverse=True)
    lines = [f"样本 {len(blocks)} 块, 候选 {len(cands)} 个, 阈值 {need}", ""]
    if hits:
        for ok, name, hx in hits[:30]:
            lines.append(f"命中 {ok}/{len(blocks)} {name} {hx}")
    else:
        lines.append("无命中（最高为 0）")
    text = "\n".join(lines)
    with open("out_tmp36.txt", "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)