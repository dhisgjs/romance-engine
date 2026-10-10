# -*- coding: utf-8 -*-
"""聊天复盘笔记存储：聊天级笔记 + 消息级笔记 + 星标。

按账号隔离，存 data/notes.json，结构：
{
  "<account>": {
    "chats": { "<talker>": {"note": "聊天总笔记", "updated": ts} },
    "msgs":  { "<talker>": { "<mid>": {"star": bool, "note": "...", "updated": ts} } }
  }
}
线程锁保护写；写入用临时文件 + os.replace 保证不半写。
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


def _acc(data: dict, account: str) -> dict:
    a = data.setdefault(account, {})
    a.setdefault("chats", {})
    a.setdefault("msgs", {})
    return a


def _chat(data: dict, account: str, talker: str) -> dict:
    return _acc(data, account)["chats"].setdefault(talker, {"note": "", "updated": 0})


def _msgs(data: dict, account: str, talker: str) -> dict:
    return _acc(data, account)["msgs"].setdefault(talker, {})


# ---------------------------------------------------------------- 聊天笔记

def set_chat_note(account: str, talker: str, note: str) -> None:
    now = int(time.time())
    with _LOCK:
        data = _load()
        c = _chat(data, account, talker)
        c["note"] = note
        c["updated"] = now
        _save(data)


def get_chat_note(account: str, talker: str) -> str:
    with _LOCK:
        data = _load()
        c = _chat(data, account, talker)
        return c.get("note", "")


# ---------------------------------------------------------------- 消息笔记 / 星标

def set_message(account: str, talker: str, mid: str, note: str = None,
                star: bool = None) -> None:
    with _LOCK:
        data = _load()
        m = _msgs(data, account, talker).setdefault(mid, {"star": False, "note": "", "updated": 0})
        changed = False
        if note is not None and note != m.get("note", ""):
            m["note"] = note
            changed = True
        if star is not None and star != m.get("star", False):
            m["star"] = star
            changed = True
        if changed:
            m["updated"] = int(time.time())
            _save(data)


def get_message(account: str, talker: str, mid: str) -> dict | None:
    with _LOCK:
        data = _load()
        return _msgs(data, account, talker).get(mid)


def starred(account: str, talker: str) -> list[tuple[str, dict]]:
    """返回 (mid, 条目) 列表，按最新标星在前。"""
    with _LOCK:
        data = _load()
        ms = _msgs(data, account, talker)
        out = [(k, v) for k, v in ms.items() if v.get("star")]
        out.sort(key=lambda kv: -kv[1].get("updated", 0))
        return out


def noted(account: str, talker: str) -> list[tuple[str, dict]]:
    """返回 (mid, 条目) 列表，含笔记的消息。"""
    with _LOCK:
        data = _load()
        ms = _msgs(data, account, talker)
        out = [(k, v) for k, v in ms.items() if v.get("note")]
        out.sort(key=lambda kv: -kv[1].get("updated", 0))
        return out


def unset_message(account: str, talker: str, mid: str) -> None:
    """删除单条消息的笔记/星标。"""
    with _LOCK:
        data = _load()
        ms = _msgs(data, account, talker)
        if mid in ms:
            del ms[mid]
            _save(data)


def set_messages_batch(account: str, talker: str, mids: list[str],
                       note: str | None = None, star: bool | None = None) -> int:
    """批量给多条消息设置笔记/星标，返回实际改动的条数。

    note="" 视为清空笔记（配合 delete_notes 用）。
    """
    if not mids:
        return 0
    now = int(time.time())
    changed = 0
    with _LOCK:
        data = _load()
        ms = _msgs(data, account, talker)
        for mid in mids:
            if not mid:
                continue
            m = ms.setdefault(mid, {"star": False, "note": "", "updated": 0})
            hit = False
            if note is not None and note != m.get("note", ""):
                m["note"] = note
                hit = True
            if star is not None and star != m.get("star", False):
                m["star"] = star
                hit = True
            if hit:
                m["updated"] = now
                changed += 1
        if changed:
            _save(data)
    return changed


def delete_notes_batch(account: str, talker: str, mids: list[str],
                       keep_star: bool = True) -> int:
    """批量删除消息笔记，返回删除条数。

    keep_star=True 时保留星标（只清笔记，整条记录不删）；
    keep_star=False 时连星标一起删（整条记录移除）。
    """
    if not mids:
        return 0
    now = int(time.time())
    removed = 0
    with _LOCK:
        data = _load()
        ms = _msgs(data, account, talker)
        for mid in mids:
            rec = ms.get(mid)
            if not rec:
                continue
            had = bool(rec.get("note")) or (not keep_star and rec.get("star"))
            if not rec.get("note") and keep_star and not rec.get("star"):
                continue
            if keep_star:
                rec["note"] = ""
                rec["updated"] = now
                if not rec.get("star"):
                    # 无星标且笔记已清空 → 整条移除
                    del ms[mid]
            else:
                del ms[mid]
            if had:
                removed += 1
        if removed:
            _save(data)
    return removed


def note_mids(account: str, talker: str) -> set[str]:
    """该聊天里所有「写了笔记」的消息 mid 集合（用于高亮显示）。"""
    with _LOCK:
        data = _load()
        ms = _msgs(data, account, talker)
        return {mid for mid, info in ms.items() if (info.get("note") or "").strip()}


# ---------------------------------------------------------------- 搜索

def search(account: str, keyword: str) -> list[dict]:
    """跨聊天搜自己的笔记/星标。返回 [{account, talker, mid, star, note, updated}]。"""
    kw = (keyword or "").strip().lower()
    out = []
    with _LOCK:
        data = _load()
        acc = data.get(account, {})
        for talker, ms in (acc.get("msgs", {}) or {}).items():
            for mid, info in ms.items():
                note = (info.get("note") or "").strip()
                if kw and kw not in note.lower():
                    continue
                out.append({
                    "account": account, "talker": talker, "mid": mid,
                    "star": bool(info.get("star")), "note": note,
                    "updated": info.get("updated", 0),
                })
    out.sort(key=lambda x: -x.get("updated", 0))
    return out


def all_notes_summary(account: str) -> dict:
    """账号笔记概览：聊天笔记条数、星标/笔记消息总数。"""
    with _LOCK:
        data = _load()
        acc = data.get(account, {})
        chats = acc.get("chats", {}) or {}
        msgs = acc.get("msgs", {}) or {}
        star = sum(1 for m in msgs.values() for i in m.values() if i.get("star"))
        noted = sum(1 for m in msgs.values() for i in m.values() if i.get("note"))
        return {
            "chat_notes": len(chats),
            "starred": star,
            "noted_msgs": noted,
        }


# ---------------------------------------------------------------- 复盘文档导出

def _sanitize(name: str) -> str:
    import re
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip(" ._")[:60] or "notes"


def export_review_markdown(account: str, store, talker: str = None,
                           keyword: str = None) -> str:
    """生成复盘文档 Markdown：指定聊天或全部（可带关键词过滤）。"""
    from .exporter import _ts

    lines = [f"# 聊天复盘笔记", "", f"账号：{account}", ""]

    def chat_title(t):
        try:
            d = store.display_name(t) if store else t
            return d or t
        except Exception:
            return t

    with _LOCK:
        data = _load()
        acc = data.get(account, {})
        chats = acc.get("chats", {}) or {}
        msgs = acc.get("msgs", {}) or {}

    kw = (keyword or "").strip().lower()
    # 聊天笔记
    chat_notes = []
    for t, c in chats.items():
        if talker and t != talker:
            continue
        note = (c.get("note") or "").strip()
        if not note:
            continue
        if kw and kw not in note.lower():
            continue
        chat_notes.append((t, note, c.get("updated", 0)))
    if chat_notes:
        lines.append("## 聊天笔记")
        lines.append("")
        for t, note, _u in chat_notes:
            lines.append(f"### {chat_title(t)}")
            lines.append(f"> {note}")
            lines.append("")
    # 消息级笔记/星标
    msg_items = []
    for t, m in msgs.items():
        if talker and t != talker:
            continue
        for mid, info in m.items():
            note = (info.get("note") or "").strip()
            if kw and not (kw in note.lower() or (info.get("star") and not kw)):
                continue
            msg_items.append((t, mid, info))
    if msg_items:
        lines.append("## 重要消息 / 笔记")
        lines.append("")
        # 需要 store 取消息原文
        lookup = {}
        if store:
            for t, mid, info in msg_items:
                try:
                    ms = store.messages(t)
                    for mm in ms:
                        if mm.get("mid") == mid:
                            lookup[(t, mid)] = mm
                            break
                except Exception:
                    pass
        for t, mid, info in msg_items:
            mm = lookup.get((t, mid))
            who = "我" if (mm and mm.get("is_self")) else ("对方")
            txt = (mm.get("text") if mm else info.get("note") or "") or ""
            txt = str(txt).replace("\n", " ")[:80]
            when = _ts(info.get("updated", 0))
            mark = "⭐" if info.get("star") else "📝"
            lines.append(f"- {mark} **{chat_title(t)}** · {when} · {who}：{txt}")
            if info.get("note"):
                lines.append(f"  - 笔记：{info['note']}")
        lines.append("")
    if not chat_notes and not msg_items:
        lines.append("（暂无笔记/星标" + (f"，关键词「{keyword}」无结果" if keyword else "") + "）")
    lines.append("")
    lines.append("---")
    lines.append("由 wx-chat-export 生成")
    return "\n".join(lines)


def export_review_html(md_text: str, title: str = "聊天复盘笔记") -> str:
    """把 Markdown 复盘文档转成简单 HTML（避免引入第三方 md 库）。"""
    import html as html_mod

    lines = md_text.splitlines()
    parts = ["<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width,initial-scale=1'>",
             f"<title>{html_mod.escape(title)}</title><style>",
             "body{margin:0;background:#f6f7fb;font:15px/1.7 -apple-system,'Segoe UI','Microsoft YaHei',sans-serif;color:#1f2329}",
             ".wrap{max-width:820px;margin:0 auto;padding:24px 18px 60px}",
             "h1{font-size:22px} h2{margin-top:26px;border-bottom:1px solid #e3e6ef;padding-bottom:6px} h3{margin-top:16px}",
             "blockquote{background:#fff8e6;border-left:4px solid #f0c33c;margin:6px 0;padding:8px 14px;border-radius:4px}",
             "ul{line-height:1.9} code{background:#f0f2f7;padding:1px 6px;border-radius:4px}",
             "</style></head><body><div class='wrap'>"]
    for ln in lines:
        if ln.startswith("# "):
            parts.append(f"<h1>{html_mod.escape(ln[2:])}</h1>")
        elif ln.startswith("## "):
            parts.append(f"<h2>{html_mod.escape(ln[3:])}</h2>")
        elif ln.startswith("### "):
            parts.append(f"<h3>{html_mod.escape(ln[4:])}</h3>")
        elif ln.startswith("> "):
            parts.append(f"<blockquote>{html_mod.escape(ln[2:])}</blockquote>")
        elif ln.startswith("- "):
            parts.append(f"<li>{html_mod.escape(ln[2:])}</li>")
        elif ln.startswith("  - "):
            parts.append(f"<li style='list-style:none'>{html_mod.escape(ln[4:])}</li>")
        elif ln.strip() == "---":
            parts.append("<hr>")
        elif ln.strip():
            parts.append(f"<p>{html_mod.escape(ln)}</p>")
    parts.append("</div></body></html>")
    return "\n".join(parts)