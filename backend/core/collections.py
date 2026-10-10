# -*- coding: utf-8 -*-
"""聊天记录合集：把选中的消息快照加入集合并附加评论，可导出 HTML/JSON。

存储为单个 JSON 文件（data/collections.json），线程锁保护读改写。
每条 item 保存消息快照（时间/发送者/内容），与评论一起自包含，
不依赖后续数据库是否还在。
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import uuid

_LOCK = threading.Lock()
_PATH = ""


def init(path: str) -> None:
    global _PATH
    _PATH = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"collections": []}, f, ensure_ascii=False, indent=2)


def _load() -> dict:
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"collections": []}
    data.setdefault("collections", [])
    return data


def _save(data: dict) -> None:
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _PATH)


def _find(data: dict, account: str, coll_id: str) -> dict | None:
    for c in data["collections"]:
        if c["id"] == coll_id and c["account"] == account:
            return c
    return None


# ---------------------------------------------------------------- API

def list_collections(account: str) -> list[dict]:
    with _LOCK:
        data = _load()
    out = []
    for c in data["collections"]:
        if c["account"] == account:
            out.append({
                "id": c["id"], "title": c["title"], "created": c["created"],
                "count": len(c["items"]),
            })
    out.sort(key=lambda x: -x["created"])
    return out


def create(account: str, title: str) -> dict:
    coll = {
        "id": uuid.uuid4().hex[:10],
        "account": account,
        "title": (title or "").strip() or f"合集 {time.strftime('%m-%d %H:%M')}",
        "created": int(time.time()),
        "items": [],
    }
    with _LOCK:
        data = _load()
        data["collections"].append(coll)
        _save(data)
    return {"id": coll["id"], "title": coll["title"], "created": coll["created"], "count": 0}


def delete(account: str, coll_id: str) -> bool:
    with _LOCK:
        data = _load()
        before = len(data["collections"])
        data["collections"] = [
            c for c in data["collections"] if not (c["id"] == coll_id and c["account"] == account)
        ]
        changed = len(data["collections"]) < before
        if changed:
            _save(data)
    return changed


def add_items(account: str, coll_id: str, items: list[dict]) -> dict:
    """items: 消息快照列表（含 mid）。按 mid 去重。"""
    cleaned = []
    for it in items:
        if not it.get("mid") or not it.get("talker"):
            continue
        cleaned.append({
            "mid": str(it["mid"]),
            "talker": str(it["talker"]),
            "ts": int(it.get("ts") or 0),
            "time": it.get("time") or "",
            "type": it.get("type"),
            "type_name": it.get("type_name") or "",
            "sender": it.get("sender") or "",
            "is_self": bool(it.get("is_self")),
            "text": it.get("text") or "",
            "comment": it.get("comment") or "",
            "added_at": int(time.time()),
        })
    with _LOCK:
        data = _load()
        coll = _find(data, account, coll_id)
        if not coll:
            raise KeyError("合集不存在")
        have = {i["mid"] for i in coll["items"]}
        added = 0
        for it in cleaned:
            if it["mid"] in have:
                continue
            coll["items"].append(it)
            have.add(it["mid"])
            added += 1
        _save(data)
    return {"added": added, "skipped": len(cleaned) - added, "total": len(coll["items"])}


def get_items(account: str, coll_id: str) -> dict | None:
    with _LOCK:
        data = _load()
        coll = _find(data, account, coll_id)
    if not coll:
        return None
    return coll


def set_comment(account: str, coll_id: str, mid: str, comment: str) -> bool:
    with _LOCK:
        data = _load()
        coll = _find(data, account, coll_id)
        if not coll:
            return False
        ok = False
        for it in coll["items"]:
            if it["mid"] == mid:
                it["comment"] = comment
                ok = True
                break
        if ok:
            _save(data)
    return ok


def remove_items(account: str, coll_id: str, mids: list[str]) -> int:
    mids = set(mids)
    with _LOCK:
        data = _load()
        coll = _find(data, account, coll_id)
        if not coll:
            return 0
        before = len(coll["items"])
        coll["items"] = [i for i in coll["items"] if i["mid"] not in mids]
        removed = before - len(coll["items"])
        if removed:
            _save(data)
    return removed


def rename(account: str, coll_id: str, title: str) -> bool:
    title = (title or "").strip()
    if not title:
        return False
    with _LOCK:
        data = _load()
        coll = _find(data, account, coll_id)
        if not coll:
            return False
        coll["title"] = title
        _save(data)
    return True


# ---------------------------------------------------------------- 导出

def _sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip(" ._")
    return name[:60] or "collection"


def export_filename(coll: dict, fmt: str) -> str:
    return _sanitize(coll["title"]) + "." + fmt


def to_json(coll: dict) -> str:
    doc = {
        "title": coll["title"],
        "account": coll["account"],
        "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(coll["created"])),
        "count": len(coll["items"]),
        "items": sorted(coll["items"], key=lambda x: x["ts"]),
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def render_html(coll: dict) -> str:
    e = html.escape
    items = sorted(coll["items"], key=lambda x: x["ts"])
    parts = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{e(coll['title'])} - 合集</title><style>",
        "body{margin:0;background:#f2f3f5;font:15px/1.65 -apple-system,'Segoe UI','Microsoft YaHei',sans-serif;color:#1f2329}",
        ".wrap{max-width:760px;margin:0 auto;padding:18px 14px 60px}",
        ".hd{background:#fff7e0;border:1px solid #f0e0b0;border-radius:10px;padding:14px 18px;margin-bottom:14px}",
        ".hd h1{margin:0 0 6px;font-size:18px}.hd .sub{color:#8a7a50;font-size:12.5px}",
        ".card{background:#fff;border-radius:10px;padding:12px 16px;margin-bottom:12px;box-shadow:0 1px 2px rgba(0,0,0,.05)}",
        ".meta{color:#9aa0a8;font-size:12px;margin-bottom:6px}",
        ".bubble{background:#f4f6f8;border-radius:8px;padding:8px 12px;white-space:pre-wrap;word-break:break-word}",
        ".comment{margin-top:8px;background:#fffbe8;border-left:3px solid #f0c33c;border-radius:4px;padding:6px 10px;font-size:13.5px;white-space:pre-wrap}",
        ".from{color:#8a9099;font-size:12px}",
        ".ft{margin-top:24px;color:#b0b5bd;font-size:12px;text-align:center}",
        "</style></head><body><div class='wrap'>",
        "<div class='hd'>",
        f"<h1>📒 {e(coll['title'])}</h1>",
        f"<div class='sub'>{len(items)} 条消息 · 创建于 {e(time.strftime('%Y-%m-%d %H:%M', time.localtime(coll['created'])))} · 导出于 {e(time.strftime('%Y-%m-%d %H:%M'))}</div>",
        "</div>",
    ]
    for it in items:
        sender = "我" if it.get("is_self") else (it.get("sender") or it.get("talker") or "")
        talker_line = e(it.get("talker") or "")
        parts.append("<div class='card'>")
        parts.append(
            f"<div class='meta'>{e(it.get('time') or '')} · {e(sender)}"
            + (f" · 来自 <span class='from'>{talker_line}</span>" if talker_line else "")
            + (f" · [{e(it.get('type_name') or '')}]" if it.get("type_name") and it.get("type") != 1 else "")
            + "</div>"
        )
        parts.append(f"<div class='bubble'>{e(it.get('text') or '')}</div>")
        if it.get("comment"):
            parts.append(f"<div class='comment'>💬 {e(it['comment'])}</div>")
        parts.append("</div>")
    parts.append("<div class='ft'>wx-chat-export 合集导出</div></div></body></html>")
    return "".join(parts)
