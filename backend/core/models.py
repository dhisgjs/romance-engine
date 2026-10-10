# -*- coding: utf-8 -*-
"""解密后的微信 4.x 数据库读取层：联系人、会话、消息解析。

4.x 结构要点（经验证，运行时均以实际表结构为准做自适应）：
- contact/contact.db: contact 表（username/alias/remark/nick_name/type/flag...）
- message/message_N.db: 每个聊天对象一张表，表名 = 前缀 + md5(talker)[:32]，
  常见前缀 Msg_/Chat_；同库还有 Name2Id 表（rowid -> user_name）做发送者映射
- session/session.db: SessionTable 会话列表
- 消息内容列带 WCDB 压缩标志列 WCDB_CT_xxx：0=明文，4=zstd
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
import urllib.parse

try:
    import zstandard as _zstd

    _DCTX = _zstd.ZstdDecompressor()
    ZSTD_AVAILABLE = True
    ZSTD_MISSING_REASON = ""
except ImportError as _e:  # pragma: no cover
    _zstd = None
    _DCTX = None
    ZSTD_AVAILABLE = False
    ZSTD_MISSING_REASON = "缺少 zstandard 库（无法解压微信压缩消息）：" + str(_e)

MSG_DB_PREFIXES = ("Msg_", "Chat_", "Name2Id_M")

# 消息类型码 -> 展示名（沿用微信通用类型；未知类型回退原文）
TYPE_NAMES = {
    1: "文本",
    3: "图片",
    34: "语音",
    37: "表情",
    42: "名片",
    43: "视频",
    44: "视频名片",
    47: "表情包",
    48: "位置",
    50: "音视频通话",
    51: "状态",
    62: "小视频",
    66: "微信红包",
    76: "转账",
    87: "快闪表情",
    10000: "系统消息",
    10002: "系统提示",
}

_CDATA_RE = re.compile(r"<title><!\[CDATA\[(.*?)\]\]></title>", re.DOTALL)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_WXID_PREFIX_RE = re.compile(r"^wxid_[A-Za-z0-9_]+:\s*\n?")
_TAG_RE = re.compile(r"<[^>]+>")
_MD5_ATTR_RE = re.compile(r'\bmd5="([0-9a-fA-F]{32})"')


def md5_32(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:32]


def wcdb_decompress(data, ct) -> str:
    """按 WCDB_CT_xxx 标志解压并解码为文本。

    ct=4 表示 zstd 压缩。zstandard 缺失或解压失败时明确返回空串，
    绝不把压缩字节当 UTF-8 解码成乱码（否则界面会出现末字缺失/乱码）。
    """
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if not isinstance(data, (bytes, bytearray)):
        return str(data)
    if ct == 4:
        if _DCTX is None:
            return ""
        try:
            data = _DCTX.decompressobj().decompress(bytes(data))
        except Exception:
            try:
                data = _DCTX.decompress(bytes(data), max_output_size=64 * 1024 * 1024)
            except Exception:
                return ""
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def extract_appmsg_title(xml_text: str) -> str:
    m = _CDATA_RE.search(xml_text) or _TITLE_RE.search(xml_text)
    if m:
        return m.group(1).strip()
    return xml_text.strip()


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info('{table}')")]


def _has(cols: list[str], *names: str) -> bool:
    return all(n in cols for n in names)


# ---------------------------------------------------------------- 联系人

class Store:
    """一个已解密账号的只读视图。"""

    def __init__(self, decrypted_root: str, account: str):
        self.root = os.path.join(decrypted_root, account)
        self.account = account
        self._name2id_cache: dict[str, dict[int, str]] = {}
        self._contact_map: dict[str, dict] | None = None
        self._msg_tables: dict[str, list[tuple[str, str]]] | None = None  # talker -> [(db, table)]
        # 自身 wxid：目录名去掉末尾 _xxxx 后缀；校验逻辑见 self_wxid()
        base = account.rsplit("_", 1)
        self._self_candidates = [account]
        if len(base) == 2 and len(base[1]) <= 5 and base[1].isalnum():
            self._self_candidates.insert(0, base[0])

    # ---- 基础 ----

    def _open(self, rel: str) -> sqlite3.Connection | None:
        path = os.path.join(self.root, rel)
        if not os.path.isfile(path):
            return None
        # immutable=1：解密产物不会再变化，跳过锁与 shm 文件（否则每次访问都会
        # 生成 -shm 导致目录 mtime 变化），读取也更快
        conn = sqlite3.connect(f"file:{urllib.parse.quote(path.replace(os.sep, '/'))}?mode=ro&immutable=1", uri=True)
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        return conn

    def _find(self, subdir: str, prefix: str) -> list[str]:
        """返回 decrypted 账号目录下 subdir/prefix*.db 的相对路径列表。"""
        d = os.path.join(self.root, subdir)
        if not os.path.isdir(d):
            return []
        return sorted(
            f for f in os.listdir(d) if f.startswith(prefix) and f.endswith(".db")
        )

    # ---- 联系人 ----

    def contacts(self) -> list[dict]:
        if self._contact_map is not None:
            return list(self._contact_map.values())
        out: dict[str, dict] = {}
        conns = [c for c in (self._open(f"contact/{f}") for f in self._find("contact", "contact")) if c]
        for conn in conns:
            try:
                cols = _table_columns(conn, "contact")
                if not cols:
                    continue
                want = [c for c in ("username", "alias", "encrypt_username", "remark",
                                    "nick_name", "type", "flag", "verify_flag") if c in cols]
                if "username" not in want:
                    continue
                sql = f"SELECT {','.join(want)} FROM contact"
                for row in conn.execute(sql):
                    rec = dict(zip(want, row))
                    username = rec.get("username") or ""
                    if not username or username in out:
                        continue
                    rec["is_chatroom"] = username.endswith("@chatroom") or username.endswith("@openim")
                    rec["is_official"] = username.startswith("gh_")
                    rec["is_self"] = username in self._self_candidates
                    nick = rec.get("nick_name") or ""
                    remark = rec.get("remark") or ""
                    rec["display"] = remark or nick or rec.get("alias") or username
                    out[username] = rec
            finally:
                conn.close()
        # 补充：Name2Id 里出现但联系人表没有的 id（罕见）
        self._contact_map = out
        return list(out.values())

    def display_name(self, wxid: str) -> str:
        c = (self._contact_map or {}).get(wxid)
        if c:
            return c.get("display") or wxid
        return wxid or "未知"

    # ---- 消息表定位 ----

    def _load_msg_tables(self) -> None:
        if self._msg_tables is not None:
            return
        self._msg_tables = {}
        by_md5: dict[str, str] = {}
        for c in self.contacts():
            by_md5[md5_32(c["username"])] = c["username"]
        rel_dbs = self._find("message", "message") + self._find("message", "biz_message")
        rel_dbs = [f"message/{f}" for f in rel_dbs if "fts" not in f and "resource" not in f]
        for rel in rel_dbs:
            conn = self._open(rel)
            if conn is None:
                continue
            try:
                names = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Msg_%'")]
                for name in names:
                    suffix = name[4:]  # 去掉 Msg_ 前缀
                    if len(suffix) == 32 and suffix.isalnum():
                        talker = by_md5.get(suffix.lower())
                        if talker:
                            self._msg_tables.setdefault(talker, []).append((rel, name))
                        else:
                            self._msg_tables.setdefault("", []).append((rel, name))
            finally:
                conn.close()

    def known_talkers(self) -> set[str]:
        self._load_msg_tables()
        return {k for k in self._msg_tables if k}

    def counts_map(self) -> dict[str, int]:
        """一次打开各消息库，一次遍历返回 {talker: 消息总数}（比逐人 count 快很多）。"""
        self._load_msg_tables()
        out: dict[str, int] = {}
        # (rel, table) -> talker 反向索引
        owner: dict[tuple[str, str], str] = {}
        by_rel: dict[str, list[str]] = {}
        for talker, tables in self._msg_tables.items():
            for rel, table in tables:
                owner[(rel, table)] = talker
                by_rel.setdefault(rel, []).append(table)
                out.setdefault(talker, 0)
        for rel, tables in by_rel.items():
            conn = self._open(rel)
            if conn is None:
                continue
            try:
                for table in tables:
                    try:
                        n = conn.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
                    except Exception:
                        n = 0
                    t = owner.get((rel, table))
                    if t:
                        out[t] = out.get(t, 0) + n
            finally:
                conn.close()
        return out

    def message_count(self, talker: str) -> int:
        self._load_msg_tables()
        total = 0
        for rel, table in self._msg_tables.get(talker, []):
            conn = self._open(rel)
            if conn is None:
                continue
            try:
                total += conn.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
            finally:
                conn.close()
        return total

    # ---- 消息读取 ----

    def _name2id(self, rel: str) -> dict[int, str]:
        if rel in self._name2id_cache:
            return self._name2id_cache[rel]
        mapping: dict[int, str] = {}
        conn = self._open(rel)
        if conn is not None:
            try:
                cols = _table_columns(conn, "Name2Id")
                col = "user_name" if "user_name" in cols else ("username" if "username" in cols else None)
                if col:
                    for rid, name in conn.execute(f"SELECT rowid, {col} FROM Name2Id"):
                        mapping[int(rid)] = name or ""
            finally:
                conn.close()
        self._name2id_cache[rel] = mapping
        return mapping

    def messages(self, talker: str, log=lambda m: None) -> list[dict]:
        """读取某聊天对象的全部消息（含文本/系统/appmsg 标题），按时间排序。"""
        self._load_msg_tables()
        self.contacts()
        rows: list[dict] = []
        targets = self._msg_tables.get(talker, [])
        if not targets:
            return rows
        self_wxid = self.self_wxid(targets)
        for rel, table in targets:
            conn = self._open(rel)
            if conn is None:
                continue
            try:
                cols = _table_columns(conn, table)
                if not _has(cols, "local_type", "create_time"):
                    log(f"    跳过 {table}：结构不完整")
                    continue
                content_col = "message_content" if "message_content" in cols else None
                src_col = "source" if "source" in cols else None
                # 链接/卡片等消息的主内容常在 compress_content / origin_source 列
                if not content_col and "compress_content" in cols:
                    content_col = "compress_content"
                if not src_col and "origin_source" in cols:
                    src_col = "origin_source"
                ct = lambda name: (f"WCDB_CT_{name}" if f"WCDB_CT_{name}" in cols else None)
                content_ct = ct("message_content") or ct("compress_content") if content_col else None
                src_ct = ct("source") or ct("origin_source") if src_col else None
                select = ["local_type", "create_time"]
                select.append("real_sender_id" if "real_sender_id" in cols else "0 AS real_sender_id")
                # 同时选 message_content 与 compress_content、source 与 origin_source（兼容不同消息）
                for _c in ("message_content", "compress_content"):
                    if _c in cols:
                        select.append(_c)
                        _cct = ct(_c)
                        if _cct:
                            select.append(_cct)
                for _s in ("source", "origin_source"):
                    if _s in cols:
                        select.append(_s)
                        _sct = ct(_s)
                        if _sct:
                            select.append(_sct)
                if "local_id" in cols:
                    select.append("local_id")
                order = "sort_seq" if "sort_seq" in cols else "create_time, local_id"
                q = f"SELECT {','.join(select)} FROM '{table}' ORDER BY {order}"
                n2i = self._name2id(rel)
                for r in conn.execute(q):
                    keys = [k.split(" AS ")[-1] for k in select]
                    rec = dict(zip(keys, r))
                    m = self._convert(rec, n2i, talker, self_wxid)
                    lid = rec.get("local_id")
                    m["mid"] = f"{rel}|{lid}" if lid is not None else f"{rel}|{m['ts']}|{m['seq']}"
                    m["time"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m["ts"])) if m["ts"] else ""
                    rows.append(m)
            finally:
                conn.close()
        rows.sort(key=lambda x: (x["ts"], x.get("seq", 0)))
        return rows

    def self_wxid(self, targets=None) -> str:
        """推断自身 wxid：优先用消息表 Name2Id 里与候选匹配的。"""
        if getattr(self, "_self_wxid", None):
            return self._self_wxid
        for cand in self._self_candidates:
            for wxid in self._all_name2ids():
                if wxid == cand:
                    self._self_wxid = cand
                    return cand
        self._self_wxid = self._self_candidates[0]
        return self._self_wxid

    def _all_name2ids(self) -> set[str]:
        ids: set[str] = set()
        self._load_msg_tables()
        rels = {rel for lst in self._msg_tables.values() for rel, _ in lst}
        for rel in rels:
            ids.update(self._name2id(rel).values())
        return ids

    def _convert(self, rec: dict, n2i: dict[int, str], talker: str, self_wxid: str) -> dict:
        t_raw = int(rec.get("local_type") or 0)
        # 4.1 的 local_type 是 64 位复合值，低 32 位才是基础消息类型
        t = t_raw & 0xFFFFFFFF if t_raw > 0xFFFFFFFF else t_raw
        # content/source 兼容不同列名（message_content / compress_content / source / origin_source）
        content = wcdb_decompress(
            rec.get("message_content") or rec.get("compress_content"),
            rec.get("WCDB_CT_message_content") or rec.get("WCDB_CT_compress_content"))
        source = wcdb_decompress(
            rec.get("source") or rec.get("origin_source"),
            rec.get("WCDB_CT_source") or rec.get("WCDB_CT_origin_source"))
        sender_id = int(rec.get("real_sender_id") or 0)
        sender_wxid = n2i.get(sender_id, "")
        is_self = sender_wxid == self_wxid or (not sender_wxid and talker == self_wxid)
        if not sender_wxid and not is_self and not talker.endswith("@chatroom"):
            # 单聊里无发送者 id 时：非对方即自己（后续由调用方校正）
            sender_wxid = ""
        text = ""
        media = None
        if t == 1:
            text = _WXID_PREFIX_RE.sub("", content or "")
        elif t in (10000, 10002):
            text = _TAG_RE.sub("", content or "").strip()
        elif t == 49:
            # 链接/卡片/文件：title 在 content（appmsg XML），source 常是 msgsource 无 title
            # 先试 content 里的 title，再试 source，最后 desc 兜底
            xml_body = content or source or ""
            text = extract_appmsg_title(xml_body)
            if not text or len(text) > 300:
                m = re.search(r"<(title|des)><!\[CDATA\[(.*?)\]\]>", xml_body, re.DOTALL)
                text = (m.group(2).strip() if m else "")[:200]
            if not text:
                m = re.search(r"<(title|des)>([^<]{2,300})</(?:title|des)>", xml_body)
                text = (m.group(2).strip() if m else "")
            if not text or text.startswith("<"):
                text = "[链接/文件]"
        elif t in (3, 47):
            # 图片/表情包：从 XML 提取 md5 供媒体接口定位文件
            m = _MD5_ATTR_RE.search(content or "") or _MD5_ATTR_RE.search(source or "")
            if m:
                media = {"md5": m.group(1).lower()}
            text = content.strip() if t == 47 else ""
            if t == 47 and text.startswith("<"):
                text = "[表情包]"
        elif t == 34:
            text = "[语音]"
        elif t == 43 or t == 62:
            text = "[视频]"
        elif t == 42:
            # 名片：提取昵称
            m = re.search(r'nickname="([^"]*)"', source or content or "")
            text = f"[名片] {m.group(1)}" if m else "[名片]"
        elif t == 48:
            text = "[位置]"
        elif t == 50:
            # 音视频通话：从 CDATA 提取状态
            m = re.search(r"<!\[CDATA\[(.*?)\]\]>", source or content or "")
            text = f"[通话] {m.group(1).strip()}" if m and m.group(1).strip() else "[通话]"
        elif t == 51:
            text = "[状态消息]"
        elif t == 76:
            text = "[微信红包]"
        else:
            # 其它未识别类型：若是 XML/超长内容 → 占位；否则显示原文
            raw = (content or "").strip()
            if not raw:
                text = ""
            elif raw.startswith("<") or len(raw) > 300:
                text = f"[{TYPE_NAMES.get(t, f'消息{t}')}]"
            else:
                text = raw[:200]
        # 发送者昵称：自己 → 空（调用方按 is_self 显示「我」）；他人 → 联系人昵称
        sender_name = ""
        if sender_wxid and not is_self:
            sender_name = self.display_name(sender_wxid) if self._contact_map else sender_wxid
        elif sender_wxid and is_self:
            sender_name = "我"
        return {
            "ts": int(rec.get("create_time") or 0),
            "seq": sender_id,
            "type": t,
            "type_name": TYPE_NAMES.get(t, f"类型{t}"),
            "sender_id": sender_id,
            "sender_wxid": sender_wxid,
            "sender": sender_name,
            "sender_name": sender_name,
            "is_self": is_self,
            "text": text,
            "media": media,
            "raw": content if t not in (1, 10000, 10002) else "",
        }

    # ---- 会话 ----

    def sessions(self) -> list[dict]:
        out = []
        for f in self._find("session", "session"):
            conn = self._open(f"session/{f}")
            if conn is None:
                continue
            try:
                tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                for tb in tables:
                    cols = _table_columns(conn, tb)
                    talker_col = next((c for c in ("str_talker_id", "talker_id", "talker", "username")
                                       if c in cols), None)
                    if not talker_col:
                        continue
                    time_col = next((c for c in ("last_timestamp", "time", "update_time") if c in cols), None)
                    for row in conn.execute(
                        f"SELECT {talker_col}{',' + time_col if time_col else ''} FROM '{tb}'"
                    ):
                        out.append({"talker": row[0], "last_time": row[1] if time_col else 0})
            finally:
                conn.close()
        return out
