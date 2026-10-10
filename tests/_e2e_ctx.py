# -*- coding: utf-8 -*-
"""真实 API 端到端验证：连发两轮追问，确认第二轮 AI 记得第一轮说了什么。

这是修复前的 bug 现场——旧逻辑每轮 force_context=True 清空历史，
第二轮提问时 AI 只看得到微信记录，看不到自己第一轮的回答。
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

client = aigen.AIClient.__new__(aigen.AIClient)
client.cfg = cfg
client.sessions = {}
client.account = "acct"
client.memory_store = None
client._lock = threading.Lock()

# 一小段真实感的微信记录
MSGS = [
    {"is_self": False, "text": "今天好累啊，加班到现在", "ts": 1757000000},
    {"is_self": True, "text": "辛苦啦，早点休息", "ts": 1757000600},
    {"is_self": False, "text": "嗯嗯，你吃了吗", "ts": 1757001200},
    {"is_self": True, "text": "还没，一起？", "ts": 1757001800},
]

print("=== 第 1 轮提问 ===")
a1 = client.chat("wxid_t", MSGS, "小鱼", user_msg="她这句话是什么意思？我该怎么回？",
                 force_context=False, timeout=180.0)
print(a1[:600])
print()

# 关键：第二轮故意不提上文，只说「那如果她已读不回呢」，
# AI 必须能看出「她」指的是上一轮讨论的对象
print("=== 第 2 轮追问（刻意不提上文）===")
a2 = client.chat("wxid_t", MSGS, "小鱼", user_msg="那如果她已读不回呢？",
                 force_context=False, timeout=180.0)
print(a2[:600])
print()

s = client.sessions["wxid_t"]
hist = s.history
print("history roles:", [m["role"] for m in hist])
print("history len:", len(hist))

OK = True


def chk(name, cond):
    global OK
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        OK = False


chk("第1轮有回答", bool(a1.strip()))
chk("第2轮有回答", bool(a2.strip()))
chk("历史含 system", any(m["role"] == "system" for m in hist))
chk("历史累积了第1答", any(a1[:30] in m["content"] for m in hist if m["role"] == "assistant"))
chk("历史累积了第2答", any(a2[:30] in m["content"] for m in hist if m["role"] == "assistant"))
chk("历史同时含两轮提问", len([m for m in hist if m["role"] == "user"]) >= 3)

print()
print("RESULT:", "ALL PASS" if OK else "SOME FAILED")
sys.exit(0 if OK else 1)