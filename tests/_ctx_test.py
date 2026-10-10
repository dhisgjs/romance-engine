# -*- coding: utf-8 -*-
"""验证 AI 多轮追问是否保留上下文（拦截网络，只看发给模型的 messages）。"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import aigen

CAPTURED = []


def fake_stream(cfg, payload, on_delta, timeout=120.0):
    CAPTURED.append([dict(m) for m in payload["messages"]])
    txt = "AI-reply-%d" % len(CAPTURED)
    on_delta(txt)
    return txt


def fake_completion(cfg, payload, timeout=120.0):
    CAPTURED.append([dict(m) for m in payload["messages"]])
    return {"choices": [{"message": {"content": "AI-reply-%d" % len(CAPTURED)}}]}


aigen._chat_completion = fake_completion
aigen._chat_completion_stream = fake_stream

cfg = dict(aigen.DEFAULT_CONFIG)
cfg["api_key"] = "test-key"
cfg["enabled"] = True

mgr = aigen.AIClient.__new__(aigen.AIClient)
mgr.cfg = cfg
mgr.sessions = {}
mgr.account = "acct"
mgr.memory_store = None
mgr._lock = threading.Lock()

msgs = [
    {"who": "peer", "text": "在吗", "ts": 1700000000},
    {"who": "me", "text": "在的", "ts": 1700000060},
    {"who": "peer", "text": "吃了吗", "ts": 1700000120},
]

Q1 = "第一问：她是不是对我没兴趣？"
Q2 = "那第二问呢？"
Q3 = "第三问？"

mgr.chat("wxid_peer", msgs, "小明", user_msg=Q1, force_context=True)
h1 = CAPTURED[-1]
mgr.chat("wxid_peer", msgs, "小明", user_msg=Q2, force_context=False)
h2 = CAPTURED[-1]
mgr.chat("wxid_peer", msgs, "小明", user_msg=Q3, force_context=False)
h3 = CAPTURED[-1]

print("turn1 n=%d %s" % (len(h1), [m["role"] for m in h1]))
print("turn2 n=%d %s" % (len(h2), [m["role"] for m in h2]))
print("turn3 n=%d %s" % (len(h3), [m["role"] for m in h3]))
print()

OK = True


def chk(name, cond):
    global OK
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        OK = False


def has(h, needle):
    return any(needle in (m.get("content") or "") for m in h)


chk("turn1 注入 system+记录注记", [m["role"] for m in h1][:2] == ["system", "user"])
chk("turn1 含聊天记录", has(h1, "聊天记录"))
chk("turn2 保留第一问", has(h2, Q1))
chk("turn2 保留第一答", has(h2, "AI-reply-1"))
chk("turn2 保留聊天记录注记", has(h2, "聊天记录"))
chk("turn2 未把历史清空", len(h2) > len(h1))
chk("turn3 保留第二问", has(h3, Q2))
chk("turn3 保留第二答", has(h3, "AI-reply-2"))
chk("turn3 仍保留第一问", has(h3, Q1))
chk("历史递增", len(h3) > len(h2) > len(h1))
tail = [m["role"] for m in h3[2:]]
chk("问答交替 user/assistant",
    all(tail[i] != tail[i + 1] for i in range(len(tail) - 1)))

print()
print("RESULT:", "ALL PASS" if OK else "SOME FAILED")
sys.exit(0 if OK else 1)
