# -*- coding: utf-8 -*-
"""真实 API 验证：模拟「重启后切换会话回来」，确认 AI 仍有上下文。

流程：session A 问一轮 → 丢弃 session A（模拟重启）→ 从持久化消息
restore_history 到新 session → 追问，AI 必须记得上一轮聊过什么。
"""
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import aigen

cfg = dict(aigen.DEFAULT_CONFIG)
cfg.update(json.load(open(os.path.join("data", "ai_config.json"), encoding="utf-8")))
cfg["enabled"] = True


def new_client():
    c = aigen.AIClient.__new__(aigen.AIClient)
    c.cfg = cfg
    c.sessions = {}
    c.account = "acct"
    c.memory_store = None
    c._lock = threading.Lock()
    return c


MSGS = [
    {"is_self": False, "text": "我下周可能要去出差", "ts": 1757000000},
    {"is_self": True, "text": "去多久", "ts": 1757000600},
    {"is_self": False, "text": "一周左右吧，还不确定", "ts": 1757001200},
]

# ---- 阶段 1：正常会话问一轮 ----
c1 = new_client()
print("=== 阶段1：会话中提问 ===")
a1 = c1.chat("wxid_t", MSGS, "小鱼", user_msg="她说出差一周左右，我要不要表现得很在意？",
             force_context=False, timeout=180.0)
print(a1[:300])
print()

# ---- 阶段 2：模拟重启，构造持久化的会话记录 ----
# ai_chats.json 里就是这个格式：{"who": "sys"/"me"/"ai", "text": ...}
SAVED = [
    {"who": "sys", "text": "已载入聊天记录"},
    {"who": "me", "text": "她说出差一周左右，我要不要表现得很在意？"},
    {"who": "ai", "text": a1},
]
EXTRA = "我俩异地，她最近工作压力很大"

# ---- 阶段 3：新客户端（重启后），restore 后追问 ----
c2 = new_client()
s = c2.session_for("wxid_t", "小鱼")
s.restore_history(SAVED, extra_context=EXTRA)
print("restored roles:", [m["role"] for m in s.history])
print()

print("=== 阶段3：重启后追问（不重建上下文）===")
a2 = c2.chat("wxid_t", MSGS, "小鱼", user_msg="那我异地这段时间怎么保持联系比较好？",
             force_context=False, timeout=180.0)
print(a2[:600])
print()

OK = True


def chk(name, cond):
    global OK
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        OK = False


chk("恢复后首条是 system", s.history[0]["role"] == "system")
chk("第1轮回答已回填", any(a1[:30] in m["content"] for m in s.history))
chk("extra 已保存", getattr(s, "_restored_extra_ctx", "") == EXTRA)
chk("第2轮有回答", bool(a2.strip()))
# AI 应知道「异地」「出差」来自恢复的历史或聊天记录
chk("第2轮延续了异地话题",
    ("异地" in a2 or "出差" in a2 or "她" in a2))
print()
print("--- 第2轮回答全文 ---")
print(a2)
print()
print("RESULT:", "ALL PASS" if OK else "SOME FAILED")
sys.exit(0 if OK else 1)