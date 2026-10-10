# -*- coding: utf-8 -*-
"""验证切换会话/重启后 restore_history 能把已存问答回填进 s.history。"""
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


aigen._chat_completion_stream = fake_stream


def fake_completion(cfg, payload, timeout=120.0):
    CAPTURED.append([dict(m) for m in payload["messages"]])
    return {"choices": [{"message": {"content": "AI-reply"}}]}


aigen._chat_completion = fake_completion

cfg = dict(aigen.DEFAULT_CONFIG)
cfg["api_key"] = "k"
cfg["enabled"] = True
client = aigen.AIClient.__new__(aigen.AIClient)
client.cfg = cfg
client.sessions = {}
client.account = "acct"
client.memory_store = None
client._lock = threading.Lock()

# 模拟 ai_chats.json 里保存的会话
SAVED = [
    {"who": "ai", "text": "\u4f60\u597d\uff0c\u6211\u662f\u604b\u7231\u6559\u7ec3\u3002"},
    {"who": "me", "text": "\u6211\u600e\u4e48\u56de\uff1f"},
    {"who": "ai", "text": "\u53ef\u4ee5\u8fd9\u4e48\u56de\u3002"},
    {"who": "me", "text": "\u90a3\u5982\u4f55\u7ea6\u597d\u5916\u51fa\uff1f"},
]

s = client.session_for("wxid_peer", "\u5c0f\u660e")
s.restore_history(SAVED, extra_context="\u4e24\u4eba\u662f\u540c\u5c97\u540c\u4e8b")
print("restored roles:", [m["role"] for m in s.history])
print("restored extra:", repr(getattr(s, "_restored_extra_ctx", "")))

OK = True


def chk(name, cond):
    global OK
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        OK = False


chk("历史非空", len(s.history) > 0)
chk("含我第一问", any("\u6211\u600e\u4e48\u56de" in m["content"] for m in s.history))
chk("含 AI 第一答", any("\u53ef\u4ee5\u8fd9\u4e48\u56de" in m["content"] for m in s.history))
chk("含我第二问", any("\u90a3\u5982\u4f55\u7ea6" in m["content"] for m in s.history))
chk("首条 AI 开场白也保留", any("\u604b\u7231\u6559\u7ec3" in m["content"] for m in s.history))
chk("extra_context 已保存", getattr(s, "_restored_extra_ctx", "") == "\u4e24\u4eba\u662f\u540c\u5c97\u540c\u4e8b")
chk("补上了 system 人格提示",
    bool(s.history) and s.history[0].get("role") == "system")
chk("注记消息带 _intro 标记", any(m.get("_intro") for m in s.history))

# 再次 restore 不应覆盖已有历史
before = len(s.history)
s.restore_history([{"who": "me", "text": "\u65b0\u7684\u95ee\u9898"}])
chk("重复 restore 不覆盖", len(s.history) == before)

# 恢复后发问，历史应继续累积
client.chat("wxid_peer", [], "\u5c0f\u660e", user_msg="\u8ffd\u95ee\u4e00\u53e5", force_context=False)
h = CAPTURED[-1]
chk("追问带上了恢复的历史", any("\u6211\u600e\u4e48\u56de" in m["content"] for m in h))
chk("追问带上本轮问题", any("\u8ffd\u95ee\u4e00\u53e5" in m["content"] for m in h))

print()
print("RESULT:", "ALL PASS" if OK else "SOME FAILED")
sys.exit(0 if OK else 1)
