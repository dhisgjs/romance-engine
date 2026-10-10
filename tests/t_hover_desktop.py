# -*- coding: utf-8 -*-
"""真实复现（desktop 平台）：QListView 显示 + 真实光标移入/移出，整窗像素对比。
Windows 平台插件下 QListView 才会真实触发 hover 重绘。"""
import os
import sys
import time

# 不设 offscreen，用默认 Windows 平台
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
import client as C  # noqa: E402

app = QtWidgets.QApplication([])
W = 820

msgs = [
    {"mid": "1", "type": 1, "text": "你好", "is_self": True, "time": "10:00"},
    {"mid": "2", "type": 1, "text": "周六有空吗？想约你去爬香山，早上八点出发，中午在山顶野餐，下午再逛逛", "is_self": False, "time": "10:01"},
    {"mid": "3", "type": 1, "text": "好啊！\n要带什么吗？", "is_self": True, "time": "10:02"},
    {"mid": "4", "type": 1, "text": "ok，周六见", "is_self": False, "time": "10:03"},
    {"mid": "5", "type": 1, "text": "对了记得穿外套", "is_self": True, "time": "10:04"},
    {"mid": "6", "type": 1, "text": "嗯嗯好的", "is_self": False, "time": "10:05"},
    {"mid": "7", "type": 1, "text": "这条消息比较长用来测试多行气泡在滚动区域里的表现应该会换行成两行显示", "is_self": True, "time": "10:06"},
]

win = QtWidgets.QWidget()
lay = QtWidgets.QVBoxLayout(win)
view = QtWidgets.QListView()
view.setModel(C.MessageModel())
view.model().set_messages(msgs, is_group=False)
view.setItemDelegate(C.MessageDelegate(view))
view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
view.setUniformItemSizes(False)
view.setMouseTracking(True)
view.setStyleSheet(f"background:{C.C_BG};border:0;outline:0;")
lay.addWidget(view)
win.resize(W, 560)
win.show()
# 移到屏幕中央，确保光标能移动到窗口内
win.move(200, 100)
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)

def grab_now(label):
    img = win.grab().toImage()
    img.save(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "tmp", f"real_{label}.png"))
    return img

def diff_count(a, b):
    n = 0
    for y in range(min(a.height(), b.height())):
        for x in range(min(a.width(), b.width())):
            if a.pixel(x, y) != b.pixel(x, y):
                n += 1
    return n

def diff_rows(a, b):
    ys = set()
    for y in range(min(a.height(), b.height())):
        for x in range(min(a.width(), b.width())):
            if a.pixel(x, y) != b.pixel(x, y):
                ys.add(y)
                break
    return sorted(ys)

img_base = grab_now("base")

# 真实光标移到第 2 行中点
r2 = view.visualRect(view.model().index(1, 0))
g2 = view.mapToGlobal(r2.center())
QtGui.QCursor.setPos(g2)
time.sleep(0.3)
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)
img_hover = grab_now("hover_r2")

# 移到第 4 行中点
r4 = view.visualRect(view.model().index(3, 0))
g4 = view.mapToGlobal(r4.center())
QtGui.QCursor.setPos(g4)
time.sleep(0.3)
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)
img_hover4 = grab_now("hover_r4")

# 移到窗口外（左上角屏幕边缘）
QtGui.QCursor.setPos(2, 2)
time.sleep(0.3)
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)
img_leave = grab_now("leave")

print("窗口位置:", win.pos().x(), win.pos().y(), " 第2行中心:", g2.x(), g2.y())
print("像素差异:")
print(f"  base → hover第2行 : {diff_count(img_base, img_hover)}")
print(f"  base → hover第4行 : {diff_count(img_base, img_hover4)}")
print(f"  hover第2 → leave  : {diff_count(img_hover, img_leave)}")
print(f"  base → leave      : {diff_count(img_base, img_leave)}")

dr = diff_rows(img_base, img_leave)
print(f"\nbase→leave 差异行: {dr}")
for i in range(view.model().rowCount()):
    rr = view.visualRect(view.model().index(i, 0))
    print(f"  行{i}: y={rr.y()} h={rr.height()} {msgs[i]['text'][:12]!r}")

win.close()