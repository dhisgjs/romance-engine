# -*- coding: utf-8 -*-
"""验证 _trim_history 在长对话下的裁剪：必须保住完整问答对，不能切半截。"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core import aigen

cfg = dict(aigen.DEFAULT_CONFIG)
s = aigen.AISession.__new__(aigen.AISession)
s.cfg = cfg
s.talker = "t"
s.peer_name = "p"
s.self_name = "me"
s.history = []
s._lock = threading.Lock()


def roles(msgs):
    return "".join(m["role"][0] for m in msgs)


# 构造：system + intro + 20 个完整问答对 + 一个待回答的提问
h = [{"role": "system", "content": "S"}, {"role": "user", "_intro": True, "content": "I"}]
for i in range(20):
    h.append({"role": "user", "content": f"Q{i}"})
    h.append({"role": "assistant", "content": f"A{i}"})
h.append({"role": "user", "content": "CURRENT"})

s.history = h
out = s._trim_history(h)
r = roles(out)
print("total in:", len(h), " out:", len(out))
print("roles:", r)

OK = True


def chk(name, cond):
    global OK
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        OK = False


chk("system 保留", out[0]["role"] == "system")
chk("intro 保留", out[1].get("_intro") is True)
chk("注记只出现一次", r.count("I") <= 1)
chk("当前提问在", out[-1]["content"] == "CURRENT")
chk("当前提问是最后一条", out[-1]["role"] == "user")
# 除了末尾未回答的提问，其余必须是 user/assistant 交替
body = [m["role"] for m in out[2:]]
alt_ok = True
i = 0
while i < len(body) - 1:
    if body[i] == "assistant":
        alt_ok = False
        break
    if body[i + 1] != "assistant":
        alt_ok = False
        break
    i += 2
chk("问答严格交替（无孤立回答）", alt_ok)
chk("未超出窗口限制", len(out) <= cfg.get("max_context_msgs", 80) + 2)

# 只剩 system 的情况
s2 = aigen.AISession.__new__(aigen.AISession)
s2.cfg = cfg
s2._lock = threading.Lock()
h2 = [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"}]
chk("只有 system+一问时 head 不误吃", roles(s2._trim_history(h2)) == "su")

# 空的和只有 assistant 的
h3 = [{"role": "system", "content": "S"}, {"role": "assistant", "content": "A"}]
r3 = roles(s3 := s2._trim_history(h3))
print("orphan assistant roles:", r3)
chk("孤立 assistant 被丢弃", r3 == "s")

# 超长场景：确认不会丢 system
s.history = h
cfg2 = dict(cfg)
cfg2["max_context_msgs"] = 4
s.cfg = cfg2
out2 = s._trim_history(h)
print("small window roles:", roles(out2))
chk("小窗口下 system 仍在", out2[0]["role"] == "system")
chk("小窗口下当前提问仍在", out2[-1]["content"] == "CURRENT")

print()
print("RESULT:", "ALL PASS" if OK else "SOME FAILED")
sys.exit(0 if OK else 1)