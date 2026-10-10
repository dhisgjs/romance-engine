# -*- coding: utf-8 -*-
"""提取与解密流水线：内存扫描 -> 密钥匹配 -> 解密目标库到本地明文目录。"""
from __future__ import annotations

import json
import os
import re
import time

from . import decrypt as _decrypt
from . import memscan

# 只解密导出/浏览需要的库（fts/resource 为纯索引；media_0 密钥通常不在内存）
WANT = ("contact/contact", "message/message_", "message/biz_message_",
        "session/session", "hardlink/hardlink", "emoticon/emoticon")


def _target_dbs(storage_dir: str) -> list[str]:
    hits = []
    for root, _dirs, files in os.walk(storage_dir):
        for f in files:
            if not f.endswith(".db"):
                continue
            rel = os.path.relpath(os.path.join(root, f), storage_dir).replace("\\", "/")
            if not any(pat in rel for pat in WANT):
                continue
            if any(x in rel for x in ("_fts", "resource", "media_", "weclaw")):
                continue
            hits.append(os.path.join(root, f))
    return sorted(hits)


def normalize_key(key: str) -> str:
    k = key.strip().strip("'\"")
    if k.lower().startswith("x'") and k.endswith("'"):
        k = k[2:-1]
    k = re.sub(r"\s+", "", k).lower()
    if not k or any(c not in "0123456789abcdef" for c in k) or len(k) not in (64, 96):
        raise ValueError("密钥格式不正确：应为 64 或 96 位十六进制字符串")
    return k


def run_extract(account: str, data_dir: str, decrypted_root: str, keys_dir: str,
                log=lambda m: None, progress=lambda p: None) -> dict:
    """在线提取：优先复用已保存密钥，缺失才扫描内存。

    首次提取需扫内存（60s+）；之后重启/换数据时密钥已缓存 → 直接解密，秒级完成。
    """
    storage_dir = os.path.join(data_dir, account, "db_storage")
    if not os.path.isdir(storage_dir):
        raise RuntimeError(f"数据库目录不存在: {storage_dir}")

    targets = _target_dbs(storage_dir)
    log(f"目标数据库 {len(targets)} 个（contact/message/session）")

    # 1) 先尝试复用已保存的密钥文件（大部分场景免扫描）
    matched: dict[str, str] = {}
    os.makedirs(keys_dir, exist_ok=True)
    keyfile = os.path.join(keys_dir, f"{account}.json")
    if os.path.isfile(keyfile):
        try:
            with open(keyfile, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            saved = {}
        for db in targets:
            rel = os.path.relpath(db, storage_dir).replace("\\", "/")
            k = saved.get(rel)
            if k and len(k) >= 64 and _decrypt.verify_key(db, k[:64]):
                matched[db] = k
        if matched:
            log(f"复用已保存密钥 {len(matched)}/{len(targets)} 个，跳过内存扫描")

    # 2) 缺失的库：只对关键库（contact/message）扫描补齐；无关紧要的（session等）跳过
    missing = [db for db in targets if db not in matched]
    critical_missing = [db for db in missing if "contact" in db or "message" in db]
    if missing and not critical_missing:
        log(f"缺 {len(missing)} 个非关键库（session 等），跳过（不影响聊天记录）")
    elif critical_missing:
        log(f"{len(critical_missing)} 个关键库需要扫描内存获取密钥…")
        result = memscan.scan_memory(log=log,
                                     progress=lambda c, t: progress(int(5 + 50 * c / max(1, t))))
        for db in missing:
            salt = memscan.db_salt(db)
            keys = result.keys_by_salt.get(salt or "") if salt else None
            if keys:
                matched[db] = next(iter(keys)) + salt
            else:
                # 纯 key 候选 HMAC 验证兜底
                for k in result.bare_keys:
                    if _decrypt.verify_key(db, k):
                        matched[db] = k + (salt or "")
                        break
        log(f"内存扫描补齐后共 {len(matched)}/{len(targets)} 个库")

    if not matched:
        raise RuntimeError(
            "未能从微信内存中找到该账号的密钥。请按顺序确认：\n"
            "1) 你要看的那个微信现在正登录着（不是别的微信）；\n"
            "2) 登录后随便打开一个聊天窗口（让数据库真正加载进内存）；\n"
            "3) 再点一次「提取密钥并解密」。\n"
            "如果本机有多个微信账号，请点「选择账号」手动选对目标账号。"
        )

    # 保存密钥文件（合并新旧）
    with open(keyfile, "w", encoding="utf-8") as f:
        json.dump({os.path.relpath(db, storage_dir).replace("\\", "/"): k
                   for db, k in matched.items()}, f, ensure_ascii=False, indent=2)
    log(f"密钥已保存: {keyfile}")

    return _decrypt_all(matched, storage_dir, decrypted_root, account, log, progress, start=60)


def run_decrypt_offline(account: str, storage_dir: str, key: str, decrypted_root: str,
                        log=lambda m: None, progress=lambda p: None) -> dict:
    """离线解密：用户手动提供密钥（64 或 96 hex）。"""
    storage_dir = os.path.normpath(storage_dir)
    if not os.path.isdir(storage_dir):
        raise RuntimeError(f"数据库目录不存在: {storage_dir}")
    key = normalize_key(key)

    targets = _target_dbs(storage_dir)
    matched: dict[str, str] = {}
    log(f"目标数据库 {len(targets)} 个，逐一验证密钥…")
    for i, db in enumerate(targets):
        progress(int(10 + 20 * i / max(1, len(targets))))
        salt_hex = memscan.db_salt(db)
        if salt_hex is None:
            continue
        if len(key) == 96:
            if key[64:] == salt_hex and _decrypt.verify_key(db, key[:64]):
                matched[db] = key
        else:
            if _decrypt.verify_key(db, key):
                matched[db] = key + salt_hex
    if not matched:
        raise RuntimeError("密钥对这些数据库验证失败：请确认密钥与账号匹配（密钥可先通过在线提取获得）")
    log(f"{len(matched)}/{len(targets)} 个库验证通过")

    keys_dir = os.path.join(os.path.dirname(decrypted_root), "keys")
    os.makedirs(keys_dir, exist_ok=True)
    with open(os.path.join(keys_dir, f"{account or 'manual'}.json"), "w", encoding="utf-8") as f:
        json.dump({os.path.relpath(db, storage_dir).replace("\\", "/"): k for db, k in matched.items()},
                  f, ensure_ascii=False, indent=2)

    return _decrypt_all(matched, storage_dir, decrypted_root, account, log, progress, start=30)


def _decrypt_all(matched: dict[str, str], storage_dir: str, decrypted_root: str, account: str,
                 log, progress, start: int = 60) -> dict:
    out_root = os.path.join(decrypted_root, account)
    os.makedirs(out_root, exist_ok=True)
    ok, failed = [], []
    total = len(matched)
    for i, (db, key) in enumerate(sorted(matched.items())):
        rel = os.path.relpath(db, storage_dir)
        out = os.path.join(out_root, rel)
        r = _decrypt.decrypt_database(db, out, key[:64], log=log)
        if r["ok"]:
            ok.append(rel)
        else:
            failed.append({"db": rel, "error": r["error"]})
            log(f"    ✗ {rel}: {r['error']}")
        progress(int(start + (95 - start) * (i + 1) / total))

    progress(100)
    summary = {
        "account": account,
        "ok": ok,
        "failed": failed,
        "keyfile": f"{account}.json",
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    log(f"解密完成：成功 {len(ok)} 个，失败 {len(failed)} 个")
    return summary
