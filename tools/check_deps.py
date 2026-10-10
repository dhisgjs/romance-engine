# -*- coding: utf-8 -*-
"""验证「别人 clone 后能否正常运行」。

不依赖本机 .venv：用当前解释器解释 requirements.txt 的依赖列表，
确认每个第三方依赖都能导入，并确认两个入口的依赖齐全。
"""
import ast
import io
import os
import sys
import sysconfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# import 名 -> pip 包名（不一致的才需要列）
PKG_OF = {
    "Crypto": "pycryptodome",
    "zstandard": "zstandard",
    "PIL": "pillow",
    "pillow_heif": "pillow-heif",
    "PySide6": "PySide6",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn[standard]",
}

reqs = []
for line in io.open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8"):
    line = line.split("#")[0].strip()
    if line:
        reqs.append(line)
print("requirements.txt 声明了 %d 个包:" % len(reqs))
for r in reqs:
    print("  -", r)

# 收集源码里所有第三方顶层 import
STDLIB = set(sys.stdlib_module_names)
# LOCAL 需含 core：backend/core 以 top-level 包被 import（backend 已加入 sys.path）
LOCAL = {"backend", "core", "tools", "tests", "client"}
# 可选依赖：只有特定命令行参数才需要，装了更好，不装不影响 run.bat
OPTIONAL = {"webview": "pywebview"}
found = set()
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames
                    if d not in {".venv", "build", "dist", ".git", "data",
                                 "__pycache__", ".pipcache", ".tmp"}]
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dirpath, fn)
        try:
            tree = ast.parse(io.open(p, encoding="utf-8").read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    found.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:      # 相对导入，忽略
                    continue
                if node.module:
                    found.add(node.module.split(".")[0])

third = sorted(m for m in found
               if m not in STDLIB and m not in LOCAL and not m.startswith("_"))
print("\n源码用到的第三方 import:", third)


def norm(name: str) -> str:
    """把包名归一化：去掉版本号/ extras，PEP 503 规范化（_ -> -，小写）。"""
    name = name.split("[")[0].strip()
    for sep in (">=", "<=", "==", ">", "<", "~=", "!="):
        name = name.split(sep)[0]
    return name.strip().lower().replace("_", "-")


# 校验覆盖情况
print()
OK = True
declared = {norm(r) for r in reqs}
for m in third:
    pkg = PKG_OF.get(m, m)
    tag = "  OK   "
    if norm(pkg) in declared:
        note = ""
    elif m in OPTIONAL:
        tag = "  OPT  "
        note = f"（可选，pip install {OPTIONAL[m]}）"
    else:
        tag = "  MISS "
        note = ""
        OK = False
    print(f"{tag}{m} (pip: {pkg}){note}")

print()
print("RESULT:", "依赖齐全" if OK else "有依赖缺失")
sys.exit(0 if OK else 1)