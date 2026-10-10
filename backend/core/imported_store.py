# -*- coding: utf-8 -*-
"""网页端导入数据的存储层。

客户端把选中的聊天推送到服务器后，数据落在 data/imported/<namespace>/：
    _meta.json    导入信息
    contacts.json 联系人/会话摘要（含 msg_count）
    chats/<safe_talker>.json  单个聊天的消息

ImportedStore 提供与 models.Store 兼容的只读接口（contacts / messages /
known_talkers / message_count / display_name），供同一套前端与导出器使用。
"""
from __future__ import annotations

import json
import os
import re
import time


def safe_ns(name: str) -> str:
    ns = re.sub(r"[^0-9A-Za-z_\-]", "_", (name or "").strip())[:40]
    return ns or "web"


def imported_root(data_dir: str) -> str:
    return os.path.join(data_dir, "imported")


def list_namespaces(data_dir: str) -> list[str]:
    root = imported_root(data_dir)
    if not os.path.isdir(root):
        return []
    out = []
    for name in os.listdir(root):
        if os.path.isfile(os.path.join(root, name, "_meta.json")):
            out.append(name)
    return sorted(out)


class ImportedStore:
    def __init__(self, namespace: str, data_dir: str):
        self.namespace = safe_ns(namespace)
        self.root = os.path.join(imported_root(data_dir), self.namespace)
        self._contacts: list[dict] | None = None
        self._display: dict[str, str] = {}
        self._tables: dict[str, list] | None = None  # talker -> file path

    # ---- 基础 ----

    def _read(self, rel: str):
        p = os.path.join(self.root, rel.replace("/", os.sep))
        if not os.path.isfile(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _chat_path(self, talker: str) -> str:
        safe = re.sub(r"[^0-9A-Za-z@_\-]", "_", talker)[:80]
        return os.path.join(self.root, "chats", safe + ".json")

    # ---- 兼容 Store 的接口 ----

    def contacts(self) -> list[dict]:
        if self._contacts is None:
            data = self._read("contacts.json") or []
            self._contacts = data
            for c in data:
                if c.get("username"):
                    self._display[c["username"]] = c.get("display") or c["username"]
        return list(self._contacts or [])

    def display_name(self, wxid: str) -> str:
        return self._display.get(wxid, wxid or "未知")

    def known_talkers(self) -> set[str]:
        self._load_tables()
        return set(self._tables.keys())

    def _load_tables(self) -> None:
        if self._tables is not None:
            return
        self._tables = {}
        chats_dir = os.path.join(self.root, "chats")
        if not os.path.isdir(chats_dir):
            return
        for f in os.listdir(chats_dir):
            if not f.endswith(".json"):
                continue
            data = self._read(f"chats/{f}")
            if not data or not data.get("talker"):
                continue
            self._tables.setdefault(data["talker"], []).append(f"chats/{f}")

    def message_count(self, talker: str) -> int:
        data = self._read_chat(talker)
        return len(data["messages"]) if data else 0

    def _read_chat(self, talker: str):
        self._load_tables()
        for rel in self._tables.get(talker, []):
            return self._read(rel)
        return None

    def self_wxid(self, targets=None) -> str:
        return ""

    def messages(self, talker: str, log=lambda m: None) -> list[dict]:
        data = self._read_chat(talker)
        if not data:
            return []
        out = []
        for m in data.get("messages", []):
            r = dict(m)
            r.setdefault("sender_wxid", "")
            r.setdefault("media", None)
            out.append(r)
        out.sort(key=lambda x: (x.get("ts", 0), x.get("mid", "")))
        return out

    # ---- 写入（接收导入） ----

    def import_chats(self, chats: list[dict]) -> dict:
        os.makedirs(os.path.join(self.root, "chats"), exist_ok=True)
        contacts = {c["username"]: c for c in (self._read("contacts.json") or [])
                    if c.get("username")}
        total_msgs = 0
        talkers = []
        for chat in chats:
            talker = chat.get("talker")
            if not talker:
                continue
            info = chat.get("contact") or {}
            msgs = chat.get("messages") or []
            clean = []
            for m in msgs:
                if m.get("ts") is None:
                    continue
                clean.append({
                    "mid": m.get("mid") or "",
                    "ts": int(m.get("ts") or 0),
                    "time": m.get("time") or "",
                    "type": int(m.get("type") or 0),
                    "type_name": m.get("type_name") or "",
                    "sender_wxid": m.get("sender_wxid") or "",
                    "sender_name": m.get("sender") or m.get("sender_name") or "",
                    "is_self": bool(m.get("is_self")),
                    "text": m.get("text") or "",
                })
            safe = re.sub(r"[^0-9A-Za-z@_\-]", "_", talker)[:80]
            path = os.path.join(self.root, "chats", safe + ".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"talker": talker, "contact": info, "messages": clean},
                          f, ensure_ascii=False)
            contacts[talker] = {
                "username": talker,
                "display": info.get("display") or talker,
                "nickname": info.get("nickname", ""),
                "remark": info.get("remark", ""),
                "alias": info.get("alias", ""),
                "is_chatroom": bool(info.get("is_chatroom")),
                "is_official": bool(info.get("is_official")),
                "is_self": False,
                "msg_count": len(clean),
            }
            total_msgs += len(clean)
            talkers.append(talker)

        clist = sorted(contacts.values(), key=lambda x: -x.get("msg_count", 0))
        with open(os.path.join(self.root, "contacts.json"), "w", encoding="utf-8") as f:
            json.dump(clist, f, ensure_ascii=False)
        meta = self._read("_meta.json") or {}
        meta.update({
            "type": "imported",
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "chats": len(contacts),
        })
        with open(os.path.join(self.root, "_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        self._contacts = None
        self._tables = None
        return {"chats": len(talkers), "messages": total_msgs}

    def delete(self) -> None:
        import shutil
        if os.path.isdir(self.root):
            shutil.rmtree(self.root)


def make_meta(namespace: str) -> dict:
    return {"type": "imported", "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
