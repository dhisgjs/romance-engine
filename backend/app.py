# -*- coding: utf-8 -*-
"""wx-chat-export 后端服务（FastAPI）。

仅处理用户本人登录账号的本地数据：读取微信进程内存提取密钥、
解密本地数据库、按联系人导出聊天记录。全部文件读写限制在项目
data 目录内，不触碰系统盘。
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根 wx-chat-export/
DATA_DIR = os.path.join(BASE_DIR, "data")
DECRYPTED_DIR = os.path.join(DATA_DIR, "decrypted")
EXPORTS_DIR = os.path.join(DATA_DIR, "exports")
KEYS_DIR = os.path.join(DATA_DIR, "keys")
TMP_DIR = os.path.join(DATA_DIR, "tmp")
for _d in (DATA_DIR, DECRYPTED_DIR, EXPORTS_DIR, KEYS_DIR, TMP_DIR):
    os.makedirs(_d, exist_ok=True)
os.environ.setdefault("TMP", TMP_DIR)
os.environ.setdefault("TEMP", TMP_DIR)

sys.path.insert(0, os.path.dirname(BASE_DIR))  # 使 `backend` 成为包

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.core import exporter, jobs, memscan, pipeline
from backend.core import collections as coll_store
from backend.core import decrypt as decrypt_mod
from backend.core import imported_store
from backend.core import media as media_mod
from backend.core import notes as notes_mod
from backend.core.exporter import _ts
from backend.core.models import Store

app = FastAPI(title="wx-chat-export", docs_url=None, redoc_url=None)

COLLECTIONS_PATH = os.path.join(DATA_DIR, "collections.json")
coll_store.init(COLLECTIONS_PATH)
NOTES_PATH = os.path.join(DATA_DIR, "notes.json")
notes_mod.init(NOTES_PATH)

# 可选访问口令：设置环境变量 WX_PASSWD 后，所有页面/接口需要 Basic 认证（用户名任意）
APP_PASSWD = os.environ.get("WX_PASSWD", "").strip()


@app.middleware("http")
async def _auth_middleware(request, call_next):
    if APP_PASSWD:
        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                userpwd = base64.b64decode(header[6:]).decode("utf-8", errors="replace")
                ok = userpwd.split(":", 1)[-1] == APP_PASSWD
            except Exception:
                ok = False
        if not ok:
            return JSONResponse(
                {"detail": "需要访问口令"},
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="wx-chat-export"'},
            )
    return await call_next(request)


# ---------------------------------------------------------------- 状态

@app.get("/api/status")
def api_status():
    pids = memscan.find_wechat_pids()
    parents = memscan._pid_parents()
    weixin_pids = [p for p in pids if parents.get(p) not in pids]
    dirs = memscan.find_data_dirs()
    accounts = []
    for d in dirs:
        for acc in memscan.list_accounts(d):
            has_dec = os.path.isdir(os.path.join(DECRYPTED_DIR, acc)) and any(
                os.scandir(os.path.join(DECRYPTED_DIR, acc))
            )
            accounts.append({
                "name": acc, "data_dir": d.replace("\\", "/"),
                "decrypted": bool(has_dec),
            })
    # 服务器场景：没有微信数据目录，但带有已解密数据
    if os.path.isdir(DECRYPTED_DIR):
        for name in sorted(os.listdir(DECRYPTED_DIR)):
            sub = os.path.join(DECRYPTED_DIR, name)
            if os.path.isdir(sub) and name not in {a["name"] for a in accounts}:
                if any(os.scandir(sub)):
                    accounts.append({"name": name, "data_dir": "", "decrypted": True})
    # 客户端导入的命名空间（网页端只显示被导入的聊天）
    for ns in imported_store.list_namespaces(DATA_DIR):
        accounts.append({"name": ns, "data_dir": "", "decrypted": True, "imported": True})
    running_jobs = [j.to_dict(with_logs=False) for j in jobs.all_jobs() if j.state == "running"]
    return {
        "wechat_running": bool(weixin_pids),
        "weixin_pids": weixin_pids,
        "data_dirs": dirs,
        "accounts": accounts,
        "running_jobs": running_jobs,
    }


# ---------------------------------------------------------------- 提取/解密

@app.post("/api/extract")
def api_extract(body: dict):
    account = body.get("account")
    data_dir = body.get("data_dir")
    if not account:
        dirs = memscan.find_data_dirs()
        if len(dirs) == 1:
            data_dir = dirs[0]
            accs = memscan.list_accounts(dirs[0])
            if len(accs) == 1:
                account = accs[0]
            else:
                raise HTTPException(400, "该数据目录下有多个账号，请指定 account")
        elif not dirs:
            raise HTTPException(400, "未找到微信数据目录，请在高级选项中手动填写")
        else:
            raise HTTPException(400, "检测到多个数据目录，请在高级选项中指定")
    elif not data_dir:
        # 只给了账号：在已知数据目录里找该账号
        for d in memscan.find_data_dirs():
            if account in memscan.list_accounts(d):
                data_dir = d
                break
        if not data_dir:
            raise HTTPException(400, f"未在已知数据目录中找到账号 {account}，请在高级选项中填写数据目录")

    def _run(job):
        job.log(f"开始在线提取密钥（账号 {account}）")
        return pipeline.run_extract(
            account, data_dir, DECRYPTED_DIR, KEYS_DIR,
            log=job.log, progress=lambda p: setattr(job, "progress", p),
        )

    job = jobs.submit("extract", {"account": account}, _run)
    return {"job_id": job.id}


@app.post("/api/decrypt-manual")
def api_decrypt_manual(body: dict):
    storage_dir = (body.get("storage_dir") or "").strip()
    key = (body.get("key") or "").strip()
    account = (body.get("account") or "manual").strip() or "manual"
    if not storage_dir or not key:
        raise HTTPException(400, "需要 storage_dir（db_storage 目录）和 key")

    def _run(job):
        job.log("开始离线解密（手动密钥）")
        return pipeline.run_decrypt_offline(
            account, storage_dir, key, DECRYPTED_DIR,
            log=job.log, progress=lambda p: setattr(job, "progress", p),
        )

    job = jobs.submit("decrypt_manual", {"account": account}, _run)
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job.to_dict()


# ---------------------------------------------------------------- 联系人/导出

def _store(account: str):
    """按账号路由：导入命名空间 → ImportedStore；否则解密数据库 Store。"""
    if os.path.isfile(os.path.join(imported_store.imported_root(DATA_DIR), account, "_meta.json")):
        return imported_store.ImportedStore(account, DATA_DIR)
    root = os.path.join(DECRYPTED_DIR, account)
    if not os.path.isdir(root):
        raise HTTPException(400, f"账号 {account} 尚未解密，请先执行提取")
    return Store(DECRYPTED_DIR, account)


_CONTACTS_CACHE: dict[str, tuple[float, dict]] = {}


_decrypted_sig_cache: dict[str, tuple[float, float]] = {}


def _decrypted_sig(account: str) -> float:
    """解密目录最新修改时间，用于缓存失效。仅当目录 mtime 变化时全 walk。"""
    root = os.path.join(DECRYPTED_DIR, account)
    # 快路径：解密产物文件数固定（解密是幂等的），目录 mtime 通常不变
    try:
        dir_mtime = os.path.getmtime(root)
    except OSError:
        return 0.0
    cached = _decrypted_sig_cache.get(account)
    if cached and cached[0] == dir_mtime:
        return cached[1]
    sig = 0.0
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            try:
                sig = max(sig, os.path.getmtime(os.path.join(dirpath, f)))
            except OSError:
                pass
    _decrypted_sig_cache[account] = (dir_mtime, sig)
    return sig


def _contacts_payload(account: str) -> dict:
    cached = _CONTACTS_CACHE.get(account)
    sig = _decrypted_sig(account)
    if cached and cached[0] == sig:
        return cached[1]
    store = _store(account)
    known = store.known_talkers()
    # 一次遍历拿全部消息数，避免逐联系人开库 COUNT
    counts = store.counts_map() if known else {}
    out = []
    for c in store.contacts():
        u = c["username"]
        out.append({
            "username": u,
            "display": c.get("display") or u,
            "nickname": c.get("nick_name") or "",
            "remark": c.get("remark") or "",
            "alias": c.get("alias") or "",
            "is_chatroom": c.get("is_chatroom", False),
            "is_official": c.get("is_official", False),
            "is_self": c.get("is_self", False),
            "msg_count": counts.get(u, 0) if u in known else 0,
        })
    for u in sorted(known - {c["username"] for c in out}):
        out.append({
            "username": u, "display": u, "nickname": "", "remark": "", "alias": "",
            "is_chatroom": u.endswith("@chatroom"), "is_official": u.startswith("gh_"),
            "is_self": False, "msg_count": counts.get(u, 0),
        })
    out.sort(key=lambda x: -x["msg_count"])
    payload = {"account": account, "contacts": out}
    _CONTACTS_CACHE[account] = (sig, payload)
    return payload


@app.get("/api/contacts")
def api_contacts(account: str, q: str = "", filter: str = "all", page: int = 0,
                 page_size: int = 300, usernames_only: int = 0):
    """联系人列表：服务端过滤 + 分页，避免每次传输/序列化全量数据。"""
    payload = _contacts_payload(account)
    items = payload["contacts"]
    ql = (q or "").strip().lower()
    out = []
    for c in items:
        if filter == "friend" and (c["is_chatroom"] or c["is_official"]):
            continue
        if filter == "group" and not c["is_chatroom"]:
            continue
        if filter == "official" and not c["is_official"]:
            continue
        if ql and ql not in c["display"].lower() and ql not in c["username"].lower() \
                and ql not in (c.get("alias") or "").lower():
            continue
        out.append(c)
    total = len(out)
    if usernames_only:
        return {"account": account, "total": total, "usernames": [c["username"] for c in out]}
    page_size = max(50, min(1000, page_size))
    page = max(0, page)
    start = page * page_size
    return {
        "account": account, "total": total, "page": page, "page_size": page_size,
        "contacts": out[start: start + page_size],
    }


_MSGS_CACHE: dict[str, tuple[float, list, dict]] = {}  # account|talker -> (sig, msgs, contact)


@app.get("/api/messages")
def api_messages(account: str, talker: str, offset: int = 0, limit: int = 400):
    limit = max(1, min(2000, limit))
    store = _store(account)
    key = f"{account}|{talker}"
    # 会话级缓存：解密目录 mtime 不变 → 全量消息复用，分页零成本
    sig = _decrypted_sig(account)
    cached = _MSGS_CACHE.get(key)
    if cached and cached[0] == sig:
        msgs, contact = cached[1], cached[2]
    else:
        contact = next((c for c in store.contacts() if c["username"] == talker), {})
        msgs = store.messages(talker)
        if len(_MSGS_CACHE) > 200:
            _MSGS_CACHE.clear()
        _MSGS_CACHE[key] = (sig, msgs, contact)
    total = len(msgs)
    offset = max(0, min(offset, total))
    page = msgs[offset: offset + limit]
    is_group = bool(contact.get("is_chatroom")) or talker.endswith("@chatroom")
    peer_display = contact.get("display") or talker
    out = []
    for m in page:
        if m["is_self"]:
            sender = "我"
        elif m.get("sender_name"):
            sender = m["sender_name"]
        elif m["sender_wxid"]:
            sender = store.display_name(m["sender_wxid"])
        else:
            sender = peer_display
        out.append({
            "mid": m["mid"], "ts": m["ts"], "time": m.get("time") or _ts(m["ts"]),
            "type": m["type"], "type_name": m["type_name"],
            "sender_wxid": m["sender_wxid"], "sender": sender,
            "is_self": m["is_self"], "text": m["text"],
            "media": m.get("media"),
        })
    return {
        "account": account, "talker": talker, "total": total,
        "offset": offset, "limit": limit,
        "is_group": is_group,
        "contact": {"username": talker, "display": peer_display,
                    "is_chatroom": is_group, "is_official": bool(contact.get("is_official"))},
        "messages": out,
    }


# ---------------------------------------------------------------- 合集

@app.get("/api/collections")
def api_collections(account: str):
    return {"account": account, "collections": coll_store.list_collections(account)}


@app.post("/api/collections/create")
def api_collections_create(body: dict):
    account = body.get("account")
    if not account:
        raise HTTPException(400, "缺少 account")
    return coll_store.create(account, body.get("title") or "")


@app.post("/api/collections/add")
def api_collections_add(body: dict):
    account = body.get("account")
    coll_id = body.get("collection_id")
    items = body.get("items") or []
    if not account or not coll_id or not items:
        raise HTTPException(400, "需要 account / collection_id / items")
    try:
        return coll_store.add_items(account, coll_id, items)
    except KeyError:
        raise HTTPException(404, "合集不存在")


@app.post("/api/collections/comment")
def api_collections_comment(body: dict):
    ok = coll_store.set_comment(
        body.get("account"), body.get("collection_id"), body.get("mid"), body.get("comment") or ""
    )
    if not ok:
        raise HTTPException(404, "合集或消息不存在")
    return {"ok": True}


@app.post("/api/collections/remove")
def api_collections_remove(body: dict):
    n = coll_store.remove_items(body.get("account"), body.get("collection_id"), body.get("mids") or [])
    return {"removed": n}


@app.post("/api/collections/delete")
def api_collections_delete(body: dict):
    ok = coll_store.delete(body.get("account"), body.get("collection_id"))
    if not ok:
        raise HTTPException(404, "合集不存在")
    return {"ok": True}


@app.post("/api/collections/rename")
def api_collections_rename(body: dict):
    ok = coll_store.rename(body.get("account"), body.get("collection_id"), body.get("title") or "")
    if not ok:
        raise HTTPException(400, "重命名失败")
    return {"ok": True}


@app.get("/api/collections/get")
def api_collections_get(account: str, collection_id: str):
    coll = coll_store.get_items(account, collection_id)
    if not coll:
        raise HTTPException(404, "合集不存在")
    return coll


@app.get("/api/collections/export")
def api_collections_export(account: str, collection_id: str, format: str = "html"):
    coll = coll_store.get_items(account, collection_id)
    if not coll:
        raise HTTPException(404, "合集不存在")
    fmt = format if format in ("html", "json") else "html"
    if fmt == "html":
        text = coll_store.render_html(coll)
    else:
        text = coll_store.to_json(coll)
    out_dir = os.path.join(EXPORTS_DIR, "_collections")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, coll_store.export_filename(coll, fmt))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return FileResponse(path, filename=os.path.basename(path))


# ---------------------------------------------------------------- 笔记 / 复盘

@app.get("/api/notes/summary")
def api_notes_summary(account: str):
    return notes_mod.all_notes_summary(account)


@app.get("/api/notes/search")
def api_notes_search(account: str, keyword: str = ""):
    items = notes_mod.search(account, keyword)
    # 补联系人显示名与消息原文
    store = None
    try:
        store = _store(account)
    except Exception:
        store = None
    cache: dict[str, dict] = {}
    out = []
    for it in items:
        t = it["talker"]
        if store:
            if t not in cache:
                try:
                    cache[t] = {m["mid"]: m for m in store.messages(t)}
                except Exception:
                    cache[t] = {}
            m = cache.get(t, {}).get(it["mid"])
            it["text"] = (m.get("text") if m else "") or ""
            it["sender"] = "我" if (m and m.get("is_self")) else "对方"
            it["display"] = store.display_name(t)
        else:
            it["text"] = ""; it["sender"] = ""; it["display"] = t
        out.append(it)
    return {"items": out}


@app.get("/api/notes/chat")
def api_notes_chat(account: str, talker: str = ""):
    return {"note": notes_mod.get_chat_note(account, talker) if talker else ""}


@app.post("/api/notes/chat")
def api_notes_chat_set(body: dict):
    account = body.get("account")
    talker = body.get("talker")
    note = (body.get("note") or "").strip()
    if not account or not talker:
        raise HTTPException(400, "需要 account / talker")
    notes_mod.set_chat_note(account, talker, note)
    return {"ok": True}


@app.post("/api/notes/message")
def api_notes_message_set(body: dict):
    account, talker, mid = body.get("account"), body.get("talker"), body.get("mid")
    if not account or not talker or not mid:
        raise HTTPException(400, "需要 account / talker / mid")
    notes_mod.set_message(account, talker, mid,
                          note=body.get("note"), star=body.get("star"))
    return {"ok": True}


@app.get("/api/notes/export")
def api_notes_export(account: str, format: str = "html", talker: str = "", keyword: str = ""):
    store = None
    try:
        store = _store(account)
    except Exception:
        store = None
    md = notes_mod.export_review_markdown(
        account, store, talker=talker or None, keyword=keyword or None)
    if format == "md":
        body = md.encode("utf-8")
        name = "复盘笔记.md"
        media = "text/markdown"
    else:
        html_txt = notes_mod.export_review_html(md, "聊天复盘笔记") if hasattr(notes_mod, "export_review_html") else md
        body = html_txt.encode("utf-8")
        name = "复盘笔记.html"
        media = "text/html"
    out_dir = os.path.join(EXPORTS_DIR, "_notes")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    with open(path, "wb") as f:
        f.write(body)
    return FileResponse(path, filename=name, media_type=media)


@app.post("/api/export")
def api_export(body: dict):
    account = body.get("account")
    usernames = body.get("usernames") or []
    fmt = body.get("format") or "html"
    if fmt not in ("html", "csv", "json"):
        raise HTTPException(400, f"不支持的格式: {fmt}")
    if not usernames:
        raise HTTPException(400, "请先勾选要导出的联系人")
    store = _store(account)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(EXPORTS_DIR, account, ts)

    def _run(job):
        results = []
        media_store = None
        try:
            media_store = _media_store(account)
        except Exception:
            media_store = None
        for i, u in enumerate(usernames):
            job.log(f"导出 {u} …")
            r = exporter.export_contact(store, u, fmt, out_dir, media_store=media_store)
            r["username"] = u
            results.append(r)
            job.progress = int(95 * (i + 1) / len(usernames))
        zip_name = None
        if len(results) > 1:
            zip_name = f"export_{ts}.zip"
            exporter.make_zip(out_dir, [r["file"] for r in results], os.path.join(out_dir, zip_name))
            job.log(f"已打包 {zip_name}")
        job.log("导出完成")
        return {
            "dir": out_dir.replace(BASE_DIR, "").lstrip("/\\").replace("\\", "/"),
            "files": results,
            "zip": zip_name,
            "total": sum(r["count"] for r in results),
        }

    job = jobs.submit("export", {"account": account, "format": fmt}, _run)
    return {"job_id": job.id}


@app.get("/api/download")
def api_download(path: str):
    # path 为相对项目根的路径（形如 data/exports/<账号>/<时间>/<文件>）
    root = os.path.realpath(EXPORTS_DIR)
    full = os.path.realpath(os.path.join(BASE_DIR, path))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        raise HTTPException(404, "文件不存在")
    return FileResponse(full, filename=os.path.basename(full))


# ---------------------------------------------------------------- 导入 / 推送 / 分析

@app.post("/api/import")
def api_import(body: dict):
    """网页端接收客户端推送的聊天（受 Basic 认证保护）。"""
    namespace = imported_store.safe_ns(body.get("namespace") or "web")
    chats = body.get("chats") or []
    if not chats:
        raise HTTPException(400, "没有可导入的聊天")
    st = imported_store.ImportedStore(namespace, DATA_DIR)
    r = st.import_chats(chats)
    return {"namespace": namespace, **r}


@app.post("/api/imported/delete")
def api_imported_delete(body: dict):
    ns = imported_store.safe_ns(body.get("namespace") or "")
    if not os.path.isdir(os.path.join(imported_store.imported_root(DATA_DIR), ns)):
        raise HTTPException(404, "命名空间不存在")
    imported_store.ImportedStore(ns, DATA_DIR).delete()
    return {"ok": True}


def _contact_brief(info: dict) -> dict:
    return {k: info.get(k, "" if k != "is_chatroom" and k != "is_official" else False)
            for k in ("username", "display", "nickname", "remark", "alias", "is_chatroom", "is_official")}


@app.post("/api/push")
def api_push(body: dict):
    """客户端（本机）把选中聊天推送到远端网页。"""
    account = body.get("account")
    server = (body.get("server") or "").strip().rstrip("/")
    namespace = imported_store.safe_ns(body.get("namespace") or "web")
    token = (body.get("token") or "").strip()
    mode = body.get("mode") or "chats"
    usernames = body.get("usernames") or []
    selected = body.get("messages") or []
    if not account or not server or not token:
        raise HTTPException(400, "需要 account / server / token")
    if not server.startswith("http"):
        server = "http://" + server

    def _run(job):
        store = _store(account)
        all_contacts = store.contacts()
        chats = []
        if mode == "selected":
            by_talker = {}
            for m in selected:
                by_talker.setdefault(m.get("talker") or "", []).append(m)
            for t, msgs in by_talker.items():
                info = next((c for c in all_contacts if c["username"] == t), {})
                chats.append({"talker": t, "contact": _contact_brief(info), "messages": msgs})
        else:
            for u in usernames:
                info = next((c for c in all_contacts if c["username"] == u), {})
                chats.append({"talker": u, "contact": _contact_brief(info),
                              "messages": store.messages(u)})
        total = sum(len(c["messages"]) for c in chats)
        if not total:
            raise RuntimeError("没有可推送的消息")
        payload = {"namespace": namespace, "chats": chats}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        job.log(f"推送 {len(chats)} 个聊天 / {total} 条消息（{len(data)//1024}KB）→ {server}")
        req = urllib.request.Request(
            server + "/api/import", data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Basic " + base64.b64encode(("wx:" + token).encode()).decode()})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                r = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"服务器返回 {e.code}：{e.read().decode('utf-8', 'replace')[:200]}")
        except Exception as e:
            raise RuntimeError(f"连接服务器失败：{e}")
        job.log(f"服务器返回：{r}")
        return r

    j = jobs.submit("push", {"account": account}, _run)
    return {"job_id": j.id}


@app.get("/api/analyze")
def api_analyze(account: str, talker: str):
    store = _store(account)
    contact = next((c for c in store.contacts() if c["username"] == talker), {})
    msgs = store.messages(talker)
    if not msgs:
        return {"talker": talker, "total": 0}

    by_hour = [0] * 24
    by_weekday = [0] * 7
    by_month: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_sender: dict[str, int] = {}
    peer_display = contact.get("display") or talker

    def sender_of(m):
        if m["is_self"]:
            return "我"
        if m.get("sender_name"):
            return m["sender_name"]
        if m.get("sender_wxid"):
            return store.display_name(m["sender_wxid"])
        return peer_display if not talker.endswith("@chatroom") else "未知"

    for m in msgs:
        lt = time.localtime(m["ts"]) if m["ts"] else None
        if lt:
            by_hour[lt.tm_hour] += 1
            by_weekday[lt.tm_wday] += 1
            ym = time.strftime("%Y-%m", lt)
            by_month[ym] = by_month.get(ym, 0) + 1
        tname = m.get("type_name") or str(m.get("type"))
        by_type[tname] = by_type.get(tname, 0) + 1
        s = sender_of(m)
        by_sender[s] = by_sender.get(s, 0) + 1

    days = sorted({m["time"][:10] for m in msgs if m.get("time")})
    self_n = sum(1 for m in msgs if m["is_self"])
    return {
        "talker": talker, "display": peer_display,
        "total": len(msgs), "self": self_n,
        "first": _ts(msgs[0]["ts"]) if msgs else "",
        "last": _ts(msgs[-1]["ts"]) if msgs else "",
        "active_days": len(days),
        "by_hour": by_hour, "by_weekday": by_weekday,
        "by_month": sorted(by_month.items()),
        "by_type": sorted(by_type.items(), key=lambda x: -x[1]),
        "top_senders": sorted(by_sender.items(), key=lambda x: -x[1])[:10],
    }


# ---------------------------------------------------------------- 媒体（图片/表情包）

MEDIA_CT = {"jpg": "image/jpeg", "png": "image/png", "gif": "image/gif",
            "webp": "image/webp", "bmp": "image/bmp", "tif": "image/tiff",
            "hevc": "image/heic", "heic": "image/heic"}

_MEDIA_STORES: dict[str, media_mod.MediaStore] = {}


def _unsupported_image(fmt: str):
    """浏览器显示不了的格式（微信自研 wxgf 容器），返回直观的 SVG 占位图。"""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200">'
        '<rect width="320" height="200" rx="10" fill="#f5f5f5" stroke="#ddd"/>'
        '<text x="160" y="90" font-size="16" text-anchor="middle" fill="#888" '
        'font-family="sans-serif">🖼 图片可在微信里查看</text>'
        f'<text x="160" y="118" font-size="12" text-anchor="middle" fill="#aaa" '
        f'font-family="sans-serif">格式：{fmt}</text></svg>'
    ).encode()
    return Response(content=svg, media_type="image/svg+xml")


def _media_store(account: str) -> media_mod.MediaStore:
    if account not in _MEDIA_STORES:
        source_base = None
        if os.name == "nt":
            for d in memscan.find_data_dirs():
                if account in memscan.list_accounts(d):
                    source_base = os.path.join(d, account)
                    break
        _MEDIA_STORES[account] = media_mod.MediaStore(account, DECRYPTED_DIR, KEYS_DIR, source_base)
    return _MEDIA_STORES[account]


@app.get("/api/media")
def api_media(account: str, md5: str, type: str = "image", variant: str = "t"):
    if not re.fullmatch(r"[0-9a-fA-F]{32}", md5 or ""):
        raise HTTPException(400, "md5 格式错误")
    md5 = md5.lower()
    store = _media_store(account)

    cache_key = f"{md5}_{variant if type == 'image' else 's'}"
    # 已解密缓存
    for fmt, ct in MEDIA_CT.items():
        cp = os.path.join(DECRYPTED_DIR, "_mediacache", account, f"{cache_key}.{fmt}")
        if os.path.isfile(cp):
            return FileResponse(cp, media_type=ct)

    if type == "image":
        # 1) 微信已渲染过的明文缓存图（无需密钥）
        cached = store.resolve_cache_image(md5)
        if cached:
            fmt = media_mod.detect_format(media_mod._read_head(cached))
            if fmt in media_mod.NEEDS_CONVERT:
                return _unsupported_image(fmt)
            return FileResponse(cached, media_type=MEDIA_CT.get(fmt, "image/jpeg"))
        # 2) 加密 .dat + 媒体密钥
        src = store.resolve_image(md5, variant if variant in ("t", "full") else "t")
        if not src:
            raise HTTPException(404, "本地没有此图片文件（微信未下载或映射缺失）")
        r = store.decrypt_file(src)
    else:
        src = store.resolve_sticker(md5)
        if not src:
            raise HTTPException(404, "本地没有此表情包文件")
        aes = store.sticker_aeskey(md5)
        if not aes:
            raise HTTPException(404, "表情包密钥缺失")
        r = store.decrypt_file(src, sticker_aeskey=aes)

    if not r:
        if store.image_key() is None:
            raise HTTPException(
                404, "此图片未在微信中打开过，软件没有缓存明文图。"
                     "请先在微信里点开这张图片，然后刷新。")
        raise HTTPException(404, "解密失败")
    plain, fmt = r
    if fmt in media_mod.NEEDS_CONVERT:
        jpg = media_mod.convert_to_jpeg(plain)
        if not jpg:
            raise HTTPException(404, f"无法转换 {fmt} 图片")
        fmt, plain = "jpg", jpg
    if fmt not in MEDIA_CT:
        raise HTTPException(404, f"不支持的图片格式 {fmt}")
    cp = os.path.join(DECRYPTED_DIR, "_mediacache", account, f"{cache_key}.{fmt}")
    with open(cp, "wb") as f:
        f.write(plain)
    return FileResponse(cp, media_type=MEDIA_CT[fmt])


@app.post("/api/media/extract-key")
def api_media_extract_key(body: dict):
    account = body.get("account")
    if not account:
        raise HTTPException(400, "缺少 account")

    def _run(job):
        store = _media_store(account)
        if store.source_base is None:
            raise RuntimeError("此服务器没有微信数据目录，请在装有微信的电脑上提取图片密钥")
        job.log("扫描微信进程内存（图片密钥 + 媒体库密钥）…")

        def prog(c, t):
            job.progress = int(90 * c / max(1, t))

        result = memscan.scan_memory(log=job.log, progress=prog)
        blocks = media_mod.find_sample_blocks(store.source_base)
        if not blocks:
            raise RuntimeError("该账号没有本地图片文件（attach 目录为空）")
        job.log(f"已知明文样本 {len(blocks)} 个，验证 {len(result.alnum)} 个候选…")
        key = media_mod.try_image_key(result.alnum, blocks)
        if key:
            os.makedirs(KEYS_DIR, exist_ok=True)
            with open(os.path.join(KEYS_DIR, f"{account}.image_key"), "w") as f:
                f.write(key)
            job.log(f"✓ 图片密钥已提取并保存")
        else:
            job.log("✗ 未找到图片密钥：请先在微信里打开 2~3 张图片，然后立即重试")

        # 顺带解密 hardlink / emoticon（若密钥在内存且尚未解密）
        cands = set()
        for kk in result.keys_by_salt.values():
            cands.update(kk)
        cands.update(result.bare_keys)
        cands.update(result.pass_candidates)
        storage = None
        if store.source_base:
            storage = os.path.join(os.path.dirname(store.source_base), "db_storage")
        for rel in ("hardlink/hardlink.db", "emoticon/emoticon.db"):
            out = os.path.join(DECRYPTED_DIR, account, rel.replace("/", os.sep))
            if os.path.isfile(out) or not storage or not os.path.isfile(os.path.join(storage, rel.replace("/", os.sep))):
                continue
            for k in cands:
                if decrypt_mod.verify_key(os.path.join(storage, rel.replace("/", os.sep)), k):
                    r = decrypt_mod.decrypt_database(
                        os.path.join(storage, rel.replace("/", os.sep)), out, k)
                    if r["ok"]:
                        job.log(f"✓ 已解密 {rel}")
                    break
        job.progress = 100
        return {"image_key": bool(key)}

    job = jobs.submit("extract-key", {"account": account}, _run)
    return {"job_id": job.id}


# ---------------------------------------------------------------- 前端静态页

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
