# -*- coding: utf-8 -*-
"""聊天记录导出器：HTML（聊天气泡样式）/ CSV / JSON，多选自动打 ZIP。"""
from __future__ import annotations

import base64
import csv
import html
import io
import json
import os
import re
import time
import zipfile

from .models import Store

MAX_ZIP_BYTES = 2 * 1024 * 1024 * 1024  # 2GB 上限
MEDIA_CT = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif",
            "webp": "image/webp", "bmp": "image/bmp"}


def _sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip(" ._")
    return name[:60] or "unnamed"


def _ts(t: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def _day(t: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


MEDIA_TYPES = {3: "图片", 34: "语音", 43: "视频", 62: "小视频", 47: "表情包", 37: "表情"}


def _make_embedder(media_store):
    """返回 (md5, type) -> data URI 的缓存函数；无媒体存储时返回 None。"""
    if media_store is None:
        return None
    cache: dict[tuple, str | None] = {}

    def embed(md5: str, mtype: int) -> str | None:
        k = (md5, mtype)
        if k in cache:
            return cache[k]
        uri = None
        try:
            if mtype == 3:
                src = media_store.resolve_image(md5, "t")
                aes = None
            else:
                src = media_store.resolve_sticker(md5)
                aes = media_store.sticker_aeskey(md5)
            if src:
                r = media_store.decrypt_file(src, sticker_aeskey=aes)
                if r and r[1] in MEDIA_CT and len(r[0]) <= 4 * 1024 * 1024:
                    uri = f"data:{MEDIA_CT[r[1]]};base64," + base64.b64encode(r[0]).decode()
        except Exception:
            uri = None
        cache[k] = uri
        return uri

    return embed


def _bubble(m: dict, sender: str, show_sender: bool, embed=None) -> str:
    e = html.escape
    t = m["type"]
    if t in (3, 47) and m.get("media") and embed:
        uri = embed(m["media"]["md5"], t)
        if uri:
            cls = "msgimg" if t == 3 else "sticker"
            body = f'<img class="{cls}" src="{uri}" alt="">'
        else:
            body = f'<span class="media">[{MEDIA_TYPES.get(t, "图片")}]</span>'
    elif t in MEDIA_TYPES:
        body = f'<span class="media">[{MEDIA_TYPES[t]}]</span>'
    elif t == 50:
        body = '<span class="media">[音视频通话]</span>'
    elif t == 48:
        body = f'<span class="media">[位置] {e(m["text"])[:80]}</span>' if m["text"] else '<span class="media">[位置]</span>'
    elif m["text"]:
        body = e(m["text"]).replace("\n", "<br>")
    elif m.get("raw"):
        body = f'<span class="media">[{e(m["type_name"])}]</span>'
    else:
        body = '<span class="media">[ unsupported ]</span>'
    sender_html = f'<div class="sender">{e(sender)}</div>' if show_sender else ""
    return f'{sender_html}<div class="bubble">{body}</div>'


def render_html(store: Store, talker: str, messages: list[dict], meta: dict, media_store=None) -> str:
    info = meta.get("contact", {})
    title = info.get("display") or talker
    e = html.escape
    n_self = sum(1 for m in messages if m["is_self"])
    is_group = bool(info.get("is_chatroom"))
    t0 = _ts(messages[0]["ts"]) if messages else "-"
    t1 = _ts(messages[-1]["ts"]) if messages else "-"

    parts = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{e(title)} - 聊天记录</title><style>",
        ":root{--green:#95ec69;--bg:#f5f5f5}",
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);font:15px/1.6 -apple-system,'Segoe UI','Microsoft YaHei',sans-serif;color:#111}",
        ".wrap{max-width:760px;margin:0 auto;padding:16px 12px 60px}",
        ".hd{background:#ededed;border-radius:10px;padding:14px 18px;margin-bottom:14px}",
        ".hd h1{margin:0 0 6px;font-size:18px}",
        ".hd .sub{color:#888;font-size:12.5px}",
        ".day{text-align:center;margin:18px 0 10px}",
        ".day span{background:#dcdcdc;color:#fff;border-radius:4px;padding:2px 10px;font-size:12px}",
        ".row{display:flex;margin:8px 0}",
        ".row.me{justify-content:flex-end}",
        ".msg{max-width:78%}",
        ".sender{color:#888;font-size:12px;margin:0 0 2px 4px}",
        ".bubble{background:#fff;border-radius:8px;padding:8px 12px;box-shadow:0 1px 1px rgba(0,0,0,.06);word-break:break-word;white-space:pre-wrap}",
        ".row.me .bubble{background:var(--green)}",
        ".media{color:#7a7a7a}",
        ".sys{text-align:center;color:#9a9a9a;font-size:12.5px;margin:8px 0}",
        ".sys span{background:#e3e3e3;border-radius:4px;padding:2px 8px;display:inline-block;max-width:90%;white-space:normal}",
        ".ft{margin-top:26px;color:#aaa;font-size:12px;text-align:center}",
        "</style></head><body><div class='wrap'>",
        "<div class='hd'>",
        f"<h1>{e(title)} <small style='color:#999;font-weight:normal'>({e(talker)})</small></h1>",
        f"<div class='sub'>共 {len(messages)} 条消息（我发送 {n_self} 条）｜ {e(t0)} ~ {e(t1)}｜导出于 {e(_ts(int(time.time())))}</div>",
        "</div>",
    ]

    last_day = ""
    embed = _make_embedder(media_store)
    for m in messages:
        d = _day(m["ts"])
        if d != last_day:
            parts.append(f"<div class='day'><span>{d}</span></div>")
            last_day = d
        if m["type"] in (10000, 10002):
            parts.append(f"<div class='sys'><span>{e(m['text'])}</span></div>")
            continue
        sender = "我" if m["is_self"] else (store.display_name(m["sender_wxid"]) if m["sender_wxid"] else (info.get("display") or talker if not is_group else ""))
        if not sender:
            sender = "未知"
        show_sender = is_group and sender != "我"
        inner = _bubble(m, sender, show_sender, embed)
        parts.append(f"<div class='row me' >" if m["is_self"] else "<div class='row'>")
        parts.append(f"<div class='msg' title='{e(_ts(m['ts']))}'>{inner}</div></div>")

    parts.append(
        "<div class='ft'>由 wx-chat-export 本地生成 · 已包含可解密的图片/表情包缩略图（未下载或加密媒体显示为占位）"
        "<br>仅限导出与查看本人账号数据</div></div></body></html>"
    )
    return "".join(parts)


def to_csv(messages: list[dict], sender_names: dict[str, str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["时间", "发送者wxid", "发送者", "是否自己", "类型", "内容"])
    for m in messages:
        name = "我" if m["is_self"] else sender_names.get(m["sender_wxid"], m["sender_wxid"] or "")
        w.writerow([_ts(m["ts"]), m["sender_wxid"], name, "是" if m["is_self"] else "否",
                    m["type_name"], m["text"] or m.get("raw", "")])
    return buf.getvalue()


def to_json(store: Store, talker: str, messages: list[dict], meta: dict) -> str:
    info = meta.get("contact", {})
    doc = {
        "talker": talker,
        "contact": {k: info.get(k) for k in ("username", "display", "nick_name", "remark", "alias") if info.get(k)},
        "exported_at": _ts(int(time.time())),
        "count": len(messages),
        "messages": [
            {
                "time": _ts(m["ts"]), "ts": m["ts"], "type": m["type"], "type_name": m["type_name"],
                "sender_wxid": m["sender_wxid"], "is_self": m["is_self"], "text": m["text"],
            }
            for m in messages
        ],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def export_contact(store: Store, talker: str, fmt: str, out_dir: str, media_store=None) -> dict:
    """导出单个联系人，返回 {'file': 文件名, 'count': 条数, 'bytes': 大小}"""
    messages = store.messages(talker)
    contact = next((c for c in store.contacts() if c["username"] == talker), {})
    meta = {"contact": contact}
    base = _sanitize(f"{contact.get('display') or talker}_{talker}")

    if fmt == "html":
        text = render_html(store, talker, messages, meta, media_store=media_store)
        fname = base + ".html"
        data = text.encode("utf-8")
    elif fmt == "csv":
        names = {c["username"]: c["display"] for c in store.contacts()}
        text = to_csv(messages, names)
        fname = base + ".csv"
        data = text.encode("utf-8-sig")  # BOM，Excel 直接打开不乱码
    elif fmt == "json":
        text = to_json(store, talker, messages, meta)
        fname = base + ".json"
        data = text.encode("utf-8")
    else:
        raise ValueError(f"未知导出格式: {fmt}")

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, fname)
    n = 1
    while os.path.exists(path):
        path = os.path.join(out_dir, f"{base}_{n}.{fmt}")
        n += 1
    with open(path, "wb") as f:
        f.write(data)
    return {"file": os.path.basename(path), "count": len(messages), "bytes": len(data)}


def make_zip(src_dir: str, files: list[str], zip_path: str) -> int:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(os.path.join(src_dir, f), f)
    return os.path.getsize(zip_path)
