# -*- coding: utf-8 -*-
"""AI 长期记忆（YourBuddy 式）：每个联系人的记忆画像，越用越懂。

存储 data/buddy_memory.json，结构：
{
  "<account>": {
    "<talker>": {
      "key_info": "长期记住的对方关键信息（昵称/喜好/职业/共同点等）",
      "style": "我的说话风格画像（语气/口头禅/常用词/句式）",
      "relation": "关系状态（认识/朋友/暧昧/对象…）",
      "conclusions": ["历史分析沉淀的结论1", "结论2"],
      "analyzed": ts,   # 最近一次分析时间
      "updates": n      # 记忆更新次数（用于排序"越聊越熟"）
    }
  }
}
"""
from __future__ import annotations

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
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _PATH)


def _entry(data: dict, account: str, talker: str) -> dict:
    a = data.setdefault(account, {})
    e = a.setdefault(talker, {})
    e.setdefault("key_info", "")
    e.setdefault("style", "")
    e.setdefault("relation", "")
    e.setdefault("conclusions", [])
    e.setdefault("analyzed", 0)
    e.setdefault("updates", 0)
    return e


def get(account: str, talker: str) -> dict | None:
    with _LOCK:
        data = _load()
        return _entry(data, account, talker)


def update(account: str, talker: str, *, key_info: str = None,
           style: str = None, relation: str = None, conclusion: str = None) -> dict:
    """更新记忆：字段为 None 表示不改。conclusion 会追加到结论列表。"""
    with _LOCK:
        data = _load()
        e = _entry(data, account, talker)
        changed = False
        if key_info is not None and key_info.strip():
            e["key_info"] = key_info.strip()[:800]
            changed = True
        if style is not None and style.strip():
            e["style"] = style.strip()[:500]
            changed = True
        if relation is not None and relation.strip():
            e["relation"] = relation.strip()[:100]
            changed = True
        if conclusion is not None and conclusion.strip():
            cons = e["conclusions"]
            cons.append(conclusion.strip()[:300])
            e["conclusions"] = cons[-20:]  # 保留最近 20 条
            changed = True
        if changed:
            e["analyzed"] = int(time.time())
            e["updates"] = e.get("updates", 0) + 1
            _save(data)
        return dict(e)


def all_talkers(account: str) -> list[dict]:
    """返回该账号所有有记忆的联系人（按更新次数/最近分析排序）。"""
    with _LOCK:
        data = _load()
        acc = data.get(account, {})
        out = []
        for talker, e in acc.items():
            out.append({"talker": talker, **e})
        out.sort(key=lambda x: -(x.get("updates", 0) * 1000 + x.get("analyzed", 0)))
        return out


def memory_count(account: str) -> int:
    with _LOCK:
        data = _load()
        return len(data.get(account, {}))
