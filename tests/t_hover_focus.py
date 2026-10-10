# -*- coding: utf-8 -*-
"""查证：QListView 默认 hover / focus 绘制是否叠加在 delegate 之上。
分别在 普通/hover/选中 态触发 viewport 重绘，对比像素。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
import client as C  # noqa: E402

app = QtWidgets.QApplication([])

msgs = [
    {"mid": "1", "type": 1, "text": "你好", "is_self": True, "time": "10:00"},
    {"mid": "2", "type": 1, "text": "周六有空吗？想约你去爬香山", "is_self": False, "time": "10:01"},
    {"mid": "3", "type": 1, "text": "好啊！\n要带什么吗？", "is_self": True, "time": "10:02"},
    {"mid": "4", "type": 1, "text": "ok，周六见", "is_self": False, "time": "10:03"},
]

win = QtWidgets.QWidget()
lay = QtWidgets.QVBoxLayout(win)
# 用和 client.py 完全一样的配置
view = QtWidgets.QListView()
view.setObjectName("chat_scroll")
view.setStyleSheet(f"QListView{{background:{C.C_BG};border:0;outline:0;}}")
view.setModel(C.MessageModel())
view.model().set_messages(msgs, is_group=False)
view.setItemDelegate(C.MessageDelegate(view))
view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
view.setUniformItemSizes(False)
view.setMouseTracking(True)
view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
view.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
lay.addWidget(view)
win.resize(700, 400)
win.show()
win.move(150, 80)
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)

def grab():
    return win.grab().toImage()

def diff(a, b):
    return sum(1 for y in range(min(a.height(), b.height()))
               for x in range(min(a.width(), b.width()))
               if a.pixel(x, y) != b.pixel(x, y))

img_base = grab()

# 1) hover
r1 = view.visualRect(view.model().index(1, 0))
QtGui.QCursor.setPos(view.viewport().mapToGlobal(r1.center()))
time.sleep(0.25)
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)
img_hover = grab()
print(f"hover 行1 差异: {diff(img_base, img_hover)}")

# 2) 点击选中（有焦点框）
r1_center = view.viewport().mapToGlobal(r1.center())
QtWidgets.QApplication.setActiveWindow(win)
for _ in range(5):
    app.processEvents()
    time.sleep(0.01)
QtGui.QCursor.setPos(r1_center)
time.sleep(0.15)
# 模拟点击
btn = QtCore.Qt.MouseButton.LeftButton
local = QtCore.QPointF(r1.center())
glob = QtCore.QPointF(r1_center)
mods = QtCore.Qt.KeyboardModifier.NoModifier
ev_p = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonPress, local, glob,
                         btn, btn, mods)
QtWidgets.QApplication.sendEvent(view.viewport(), ev_p)
ev_r = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseButtonRelease, local, glob,
                         btn, QtCore.Qt.MouseButton.NoButton, mods)
QtWidgets.QApplication.sendEvent(view.viewport(), ev_r)
time.sleep(0.25)
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)
img_sel = grab()
print(f"点击选中 差异: {diff(img_base, img_sel)}")

# 3) 选中后移开鼠标（focus 框可能仍显示）
QtGui.QCursor.setPos(2, 2)
time.sleep(0.25)
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)
img_sel_leave = grab()
print(f"选中后移开 差异: {diff(img_base, img_sel_leave)}")

# 4) 滚动（触发重绘）
sb = view.verticalScrollBar()
sb.setValue(2)
time.sleep(0.25)
for _ in range(10):
    app.processEvents()
    time.sleep(0.02)
img_scroll = grab()
print(f"滚动后 差异(整体): {diff(img_base, img_scroll)}")

print("\n结论:")
if diff(img_base, img_hover) == 0 and diff(img_base, img_sel_leave) == 0:
    print("  hover/选取后移开 完全无差异 → delegate 绘制稳定")
else:
    print("  有差异 → 需进一步定位")
if diff(img_base, img_sel) != 0:
    print("  点击选中产生差异（选中态/焦点框）→ 这是期望的选中效果")
win.close()