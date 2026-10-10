# -*- coding: utf-8 -*-
"""新增 backend/core/ai_chats.py：AI 聊天会话持久化（多会话 + 保存/删除/重命名）

结构（data/ai_chats.json）：
{
  "<account>": {
    "<talker>": {
      "title": "和小美的聊天",
      "updated": 1700000000,
      "created": 1690000000,
      "extra_context": "我们见过两次面…",
      "messages": [{"who": "me|ai|sys", "text": "..."}, ...]
    }
  }
}
按账号隔离；线程锁 + 临时文件原子写。
"""
import json
import os
import threading
import time

_LOCK = threading.Lock()
_PATH = ""


def init(path: str) -> None:
    global _PATH
    _PATH = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False)


def _load() -> dict:
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict) -> None:
    if not _PATH:
        return
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _PATH)


def _acc(data: dict, account: str) -> dict:
    return data.setdefault(account or "", {})


# ------------------------------------------------------------ 会话读写

def save_conversation(account: str, talker: str, messages: list[dict],
                      extra_context: str = "", title: str = "") -> None:
    """保存（覆盖）某个联系人的 AI 聊天记录。messages 为 [{who,text}, ...]。"""
    now = int(time.time())
    with _LOCK:
        data = _load()
        acc = _acc(data, account)
        old = acc.get(talker) or {}
        acc[talker] = {
            "title": title or old.get("title") or "",
            "created": old.get("created") or now,
            "updated": now,
            "extra_context": extra_context,
            "messages": [{"who": m.get("who", "ai"), "text": m.get("text", "")}
                         for m in messages if m.get("text")],
        }
        _save(data)


def load_conversation(account: str, talker: str) -> dict:
    """读取某个联系人的 AI 聊天记录；不存在返回空结构。"""
    with _LOCK:
        data = _load()
        c = _acc(data, account).get(talker) or {}
        return {
            "title": c.get("title", ""),
            "extra_context": c.get("extra_context", ""),
            "messages": c.get("messages", []) or [],
            "updated": c.get("updated", 0),
        }


def set_extra_context(account: str, talker: str, extra_context: str) -> None:
    """单独保存「补充场景」（不覆盖消息）。"""
    with _LOCK:
        data = _load()
        acc = _acc(data, account)
        c = acc.setdefault(talker, {"messages": [], "created": int(time.time())})
        c["extra_context"] = extra_context
        c["updated"] = int(time.time())
        _save(data)


def delete_conversation(account: str, talker: str) -> None:
    """删除某个联系人的 AI 聊天记录。"""
    with _LOCK:
        data = _load()
        acc = _acc(data, account)
        if talker in acc:
            del acc[talker]
            _save(data)


def clear_messages(account: str, talker: str) -> None:
    """清空某个会话的消息，但保留补充场景。"""
    with _LOCK:
        data = _load()
        acc = _acc(data, account)
        c = acc.setdefault(talker, {"extra_context": ""})
        c["messages"] = []
        c["updated"] = int(time.time())
        _save(data)


def rename_conversation(account: str, talker: str, title: str) -> None:
    with _LOCK:
        data = _load()
        acc = _acc(data, account)
        c = acc.setdefault(talker, {"messages": [], "created": int(time.time())})
        c["title"] = (title or "").strip()[:60]
        c["updated"] = int(time.time())
        _save(data)


def list_conversations(account: str) -> list[dict]:
    """列出该账号所有 AI 会话，按更新时间倒序。"""
    with _LOCK:
        data = _load()
        acc = _acc(data, account)
        out = []
        for talker, c in acc.items():
            msgs = c.get("messages") or []
            out.append({
                "talker": talker,
                "title": c.get("title", "") or "",
                "updated": c.get("updated", 0),
                "count": len(msgs),
            })
        out.sort(key=lambda x: -x["updated"])
        return out
