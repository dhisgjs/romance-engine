# -*- coding: utf-8 -*-
"""上传前脱敏：把测试脚本里的真实标识符 / 本机路径 / API 密钥换成占位符。

只改 tests/ 下的排查脚本，不动 backend/ 与 client.py 的业务逻辑。
幂等：重复运行不会二次替换。

真实密钥不写在本文件里——通过环境变量传入：
    set SANITIZE_API_KEY=<你的真实 key>
    python tools/sanitize.py
未设置时只做 wxid / 路径的脱敏。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")

SUBS = [
    # 本机真实微信数据根目录
    (re.compile(r"D:\\\\personal\\\\Documents\\\\xwechat_files"),
     "D:/WeChatFiles"),
]

# 真实账号 / 好友 wxid：具体值从环境变量传入，不落盘
_env_wxid = os.environ.get("SANITIZE_WXID", "").strip()
if _env_wxid:
    SUBS.insert(0, (re.compile(re.escape(_env_wxid) + r"_efcf"), "wxid_your_account_efcf"))
    SUBS.insert(0, (re.compile(re.escape(_env_wxid)), "wxid_your_account"))

# 真实 API 密钥：通用形态匹配 + 可选的具体值（从环境变量读，不落盘）
SUBS.insert(0, (re.compile(r"sk-[a-f0-9]{32,}"), "sk-REPLACE_WITH_YOUR_KEY"))
_env_key = os.environ.get("SANITIZE_API_KEY", "").strip()
if _env_key:
    SUBS.insert(0, (re.compile(re.escape(_env_key)), "sk-REPLACE_WITH_YOUR_KEY"))

changed = []
for name in sorted(os.listdir(TESTS)):
    if not name.endswith(".py"):
        continue
    p = os.path.join(TESTS, name)
    src = io.open(p, encoding="utf-8").read()
    out = src
    for pat, rep in SUBS:
        out = pat.sub(rep, out)
    if out != src:
        io.open(p, "w", encoding="utf-8", newline="\n").write(out)
        changed.append(name)

print("sanitized %d files:" % len(changed))
for n in changed:
    print("  ", n)