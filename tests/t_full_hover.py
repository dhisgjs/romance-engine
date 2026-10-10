# -*- coding: utf-8 -*-
"""完整真实复现：启动真 MainWindow + 真实账号，自动移动鼠标扫过各行，
高频截图像素对比，抓 hover 瞬态闪烁（时间/气泡错位）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
import client as C  # noqa: E402

app = QtWidgets.QApplication([])

# 真实账号
ACCT = "wxid_your_account_efcf"
DEC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "decrypted")

win = None
try:
    win = C.MainWindow()
    win.show()
    for _ in range(50):
        app.processEvents()
        time.sleep(0.02)
    # 加载真实账号（绕过 UI 选择流程）
    win._load_account(ACCT, os.path.dirname(DEC))
    for _ in range(80):
        app.processEvents()
        time.sleep(0.02)
    print("账号加载:", win.account)
    print("联系人数量:", len(win._contact_display))

    # 选一个会话（优先消息多、有真实聊天的，避开 notifymessage）
    if not win._contact_display:
        print("无联系人，退出")
        sys.exit(0)
    talker = None
    for u, _d, cnt in win._contact_display:
        if u != "notifymessage" and cnt >= 5:
            talker = u
            break
    if talker is None:
        talker = win._contact_display[0][0]
    print("选会话:", talker)
    win._show_chat(talker)
    for _ in range(60):
        app.processEvents()
        time.sleep(0.02)
    print("当前消息数:", len(win._cur_msgs))
    # 关掉 AI 自动分析线程的干扰：切到无 AI 状态不影响渲染，这里忽略
    print("消息类型分布:", {})
    from collections import Counter
    tc = Counter(m.get("type") for m in win._cur_msgs)
    print("  ", dict(tc))

    view = win.chat_view
    view.verticalScrollBar().setValue(0)
    app.processEvents()
    time.sleep(0.2)

    # 先把窗口移到屏幕可见位置
    win.move(150, 80)
    app.processEvents()
    time.sleep(0.3)

    def grab_now(label):
        img = win.grab().toImage()
        img.save(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "data", "tmp", f"full_{label}.png"))
        return img

    def diff(a, b):
        return sum(1 for y in range(min(a.height(), b.height()))
                   for x in range(min(a.width(), b.width()))
                   if a.pixel(x, y) != b.pixel(x, y))

    img_base = grab_now("base")
    diffs = []
    # 从顶部往下扫，每行停一下截图
    for i in range(min(12, view.model().rowCount())):
        r = view.visualRect(view.model().index(i, 0))
        if not r.isValid() or r.y() < 0 or r.y() > view.viewport().height():
            continue
        g = view.viewport().mapToGlobal(r.center())
        QtGui.QCursor.setPos(g)
        time.sleep(0.06)
        for _ in range(6):
            app.processEvents()
            time.sleep(0.02)
        img = grab_now(f"row{i}")
        d = diff(img_base, img)
        diffs.append((i, d))
        print(f"  行{i} hover 差异: {d}")

    # 移出
    QtGui.QCursor.setPos(2, 2)
    time.sleep(0.25)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    img_leave = grab_now("leave")
    print("\n最终 base→leave 差异:", diff(img_base, img_leave))
    max_diff = max((d for _, d in diffs), default=0)
    print("最大 hover 差异:", max_diff)
    print("\n" + ("PASS: hover 稳定，无闪烁" if max_diff == 0 and diff(img_base, img_leave) == 0
                  else "FAIL: hover 有像素变化（闪烁）"))
finally:
    if win:
        win.close()