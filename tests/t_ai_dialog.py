# -*- coding: utf-8 -*-
"""AI 设置对话框回归：模型下拉框、一键测试按钮、保存字段、错误提示。
离屏渲染；一键测试发真实请求到 inferaiapi 网关（只读）。"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtWidgets  # noqa: E402
import client as C  # noqa: E402

app = QtWidgets.QApplication([])
failures = []
def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

cfg = {
    "api_url": "https://inferaiapi.com/v1/chat/completions",
    "api_key": "sk-REPLACE_WITH_YOUR_KEY",
    "model": "mimo-v2.6-pro",
    "enabled": True,
    "max_context_msgs": 80,
    "persona": "幽默毒舌",
    "auto_copy": False,
}

print("== 1) 对话框构建 ==")
dlg = C.AISettingsDialog(cfg)
check("默认模型 = mimo-v2.6-pro", dlg.ed_model.currentText() == "mimo-v2.6-pro",
      dlg.ed_model.currentText())
check("下拉含 7 个预设", dlg.ed_model.count() >= 7, str(dlg.ed_model.count()))
check("API 地址字段回填", dlg.ed_api.text() == cfg["api_url"])
check("密钥字段回填", dlg.ed_key.text() == cfg["api_key"])
check("启用勾选", dlg.cb_enable.isChecked() is True)
check("人格底色回填", dlg.ed_persona.toPlainText() == "幽默毒舌")

print("\n== 2) 切换模型 ==")
dlg.ed_model.setCurrentText("deepseek-v4-flash")
check("切换后读取正确", dlg.ed_model.currentText() == "deepseek-v4-flash")

print("\n== 3) 保存字段 ==")
dlg._ok()
check("保存后 model", dlg.cfg.get("model") == "deepseek-v4-flash", str(dlg.cfg.get("model")))
check("保存后 api_url", dlg.cfg.get("api_url") == cfg["api_url"])
check("保存后 enabled", dlg.cfg.get("enabled") is True)

print("\n== 4) 一键测试（真实请求） ==")
dlg2 = C.AISettingsDialog(cfg)
dlg2.btn_test.clicked.emit()
deadline = time.time() + 100
while time.time() < deadline:
    app.processEvents()
    if dlg2.btn_test.isEnabled() and "测试中" not in dlg2.lbl_test.text():
        break
    time.sleep(0.5)
msg = dlg2.lbl_test.text()
print("  测试结果:", msg)
check("一键测试返回结果", "连接成功" in msg or "失败" in msg, msg)
check("按钮恢复可用", dlg2.btn_test.isEnabled())

print("\n== 5) 错误模型提示（不发请求，纯看 friendly_error 文案） ==")
from backend.core.aigen import test_connection
r = test_connection({"api_url": cfg["api_url"], "api_key": "sk-wrong",
                     "model": "mimo-v2.6-pro"}, timeout=30)
check("坏 key → 中文提示", "密钥" in r["msg"], r["msg"])

print()
if failures:
    print(f"FAIL: {failures}")
    sys.exit(1)
print("ALL PASS: AI 设置对话框回归 全部正常")
