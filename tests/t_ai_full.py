# -*- coding: utf-8 -*-
"""AI 全功能真机回归：连接测试 / 建议 / 复盘 / 自由对话 / 记忆 / 错误处理。
用真实 data/ai_config.json，只读网络请求，写测试记忆到 F 盘并清理。"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core import aigen  # noqa: E402
from backend.core import buddy_memory  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TMP = os.path.join(DATA, "tmp")
os.makedirs(TMP, exist_ok=True)

failures = []
def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

msgs = [
    {"mid": "1", "is_self": False, "text": "周末有空吗？", "type": 1, "ts": int(time.time()) - 3600},
    {"mid": "2", "is_self": True, "text": "有啊，怎么啦", "type": 1, "ts": int(time.time()) - 3500},
    {"mid": "3", "is_self": False, "text": "想约你去看电影，最近有部新片不错", "type": 1, "ts": int(time.time()) - 3400},
    {"mid": "4", "is_self": True, "text": "可以啊，什么片？", "type": 1, "ts": int(time.time()) - 3300},
    {"mid": "5", "is_self": False, "text": "《流浪地球3》，听说特效特别棒", "type": 1, "ts": int(time.time()) - 3200},
    {"mid": "6", "is_self": False, "text": "你周六下午有空吗？", "type": 1, "ts": int(time.time()) - 300},
]

print("== 1) 配置加载 ==")
client = aigen.AIClient(DATA)
check("配置指向 inferaiapi", "inferaiapi" in client.cfg.get("api_url", ""))
check("模型 = mimo-v2.6-pro", client.cfg.get("model") == "mimo-v2.6-pro")
check("已启用且带 key", client.enabled())

print("\n== 2) 连接测试 ==")
r = aigen.test_connection(client.cfg, timeout=90)
check("连接成功", r["ok"], r["msg"])
print(f"   {r['msg']}")

print("\n== 3) 建议生成（首次全量） ==")
mem_path = os.path.join(TMP, "ai_test_memory.json")
if os.path.exists(mem_path):
    os.remove(mem_path)
buddy_memory.init(mem_path)
client.memory_store = buddy_memory
client.account = "test_acc"          # 记忆按账号隔离，必须设置（GUI 里由 _load_account 注入）
client.reset_session("t1")
t0 = time.time()
text = client.suggest("t1", msgs, peer_name="她", force_rebuild=True, timeout=120)
dt = time.time() - t0
# 首次全量 = 整体分析（prompt 告诉 AI 先分析、等新消息再出方案），不含 A/B/C 是预期的
check("建议非空", bool(text), "空")
check("首次含分析内容", ("分析" in text or "兴趣" in text or "对方" in text), text[:120])
print(f"   [{dt:.0f}s] {text[:100]!r}")

print("\n== 4) 增量建议 ==")
msgs2 = list(msgs) + [{"mid": "7", "is_self": False, "text": "那就说定了！周六见", "type": 1,
                       "ts": int(time.time())}]
t0 = time.time()
text2 = client.suggest("t1", msgs2, peer_name="她", force_rebuild=False, timeout=120)
check("增量建议非空", bool(text2), "空")
check("增量含方案 A/B/C", all(s in text2 for s in ("A", "B", "C")), text2[:150])
print(f"   [{time.time()-t0:.0f}s] {text2[:100]!r}")

print("\n== 5) AI 复盘 ==")
t0 = time.time()
rev = client.review("t1", msgs2, timeout=120)
check("复盘非空", bool(rev), "空")
check("复盘结构完整", "【对方状态】" in rev and "【我做得好的】" in rev, rev[:150])
print(f"   [{time.time()-t0:.0f}s] {rev[:100]!r}")

print("\n== 6) 自由对话 ==")
t0 = time.time()
ans = client.chat("t1", msgs2, peer_name="她", user_msg="她在暗示我约会吗？", timeout=120)
check("自由对话非空", bool(ans), "空")
print(f"   [{time.time()-t0:.0f}s] {ans[:100]!r}")

print("\n== 7) 长期记忆 ==")
m = buddy_memory.get("test_acc", "t1")
check("沉淀风格", bool(m and m.get("style")))
check("沉淀结论", bool(m and m.get("conclusions")))
print(f"   style={m and m.get('style','')[:40]!r} conc={len((m or {}).get('conclusions') or [])}")

print("\n== 8) 错误处理 ==")
r = aigen.test_connection(dict(client.cfg, api_key="sk-wrong"), timeout=40)
check("坏 key 识别", "密钥" in r["msg"], r["msg"])
r2 = aigen.test_connection(dict(client.cfg, model="nope-xyz"), timeout=40)
check("坏模型识别", not r2["ok"], r2["msg"])

try:
    os.remove(mem_path)
except Exception:
    pass

print()
if failures:
    print(f"FAIL: {failures}")
    sys.exit(1)
print("ALL PASS: AI 全功能真机回归 全部正常")