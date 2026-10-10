# -*- coding: utf-8 -*-
"""验证 ChatListView：真实会话 hover/滚动像素稳定 + 无闪烁 + 渲染正常。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
import client as C  # noqa: E402

app = QtWidgets.QApplication([])
ACCT = "wxid_your_account_efcf"
DEC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "decrypted")

win = C.MainWindow()
win.show()
for _ in range(50):
    app.processEvents()
    time.sleep(0.02)
win._load_account(ACCT, os.path.dirname(DEC))
for _ in range(80):
    app.processEvents()
    time.sleep(0.02)

# 选有真实文本聊天的会话
best = None
best_txt = -1
for u, d, cnt in win._contact_display:
    if u == "notifymessage":
        continue
    try:
        msgs = win.store.messages(u)
    except Exception:
        continue
    n = sum(1 for m in msgs if m.get("type") == 1)
    if n > best_txt:
        best_txt = n
        best = (u, d, msgs)
    if best_txt > 40:
        break
print("会话:", best[0], "文本消息:", best_txt)
win._show_chat(best[0])
for _ in range(60):
    app.processEvents()
    time.sleep(0.02)

view = win.chat_view
print("view 类型:", type(view).__name__)
win.move(120, 60)
app.processEvents()
time.sleep(0.3)

def diff(a, b):
    return sum(1 for y in range(min(a.height(), b.height()))
               for x in range(min(a.width(), b.width()))
               if a.pixel(x, y) != b.pixel(x, y))

img_base = win.grab().toImage()
total = 0
maxd = 0
t0 = time.time()
# 扫过可见行 + 滚动
for i in range(min(30, view.model().rowCount())):
    r = view.visualRect(view.model().index(i, 0))
    if not r.isValid() or r.y() < 0 or r.y() > view.viewport().height():
        continue
    QtGui.QCursor.setPos(view.viewport().mapToGlobal(r.center()))
    time.sleep(0.03)
    for _ in range(3):
        app.processEvents()
    img = win.grab().toImage()
    d = diff(img_base, img)
    total += d
    maxd = max(maxd, d)
# 移出
QtGui.QCursor.setPos(2, 2)
time.sleep(0.2)
for _ in range(5):
    app.processEvents()
img_leave = win.grab().toImage()
d_leave = diff(img_base, img_leave)
print(f"累计 hover 差异: {total}, 最大: {maxd}, 移出后: {d_leave}, 耗时 {time.time()-t0:.0f}s")

# 滚动测试（ChatListView 每帧整刷，确认性能）
sb = view.verticalScrollBar()
t1 = time.time()
sb.setValue(sb.value() + 400)
for _ in range(10):
    app.processEvents()
    time.sleep(0.01)
img_s = win.grab().toImage()
print(f"滚动后渲染正常: 非背景像素={sum(1 for y in range(img_s.height()) for x in range(img_s.width()) if QtGui.QColor(img_s.pixel(x,y)).name().lower()!='#f2f3f5')}")
win.close()
print("PASS 稳定无闪烁" if maxd == 0 and d_leave == 0 else "FAIL 有差异")