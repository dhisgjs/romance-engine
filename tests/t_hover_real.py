# -*- coding: utf-8 -*-
"""真实复现：QListView + 多行混合高度，鼠标移入/移出前后整窗截图像素对比。
定位 hover 闪烁的具体来源（行高错位 / 绘制残留 / 局部重绘裁剪）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
import client as C  # noqa: E402

app = QtWidgets.QApplication([])
W = 820

# 混合高度消息：短文本、长文本、图片、多行
msgs = [
    {"mid": "1", "type": 1, "text": "你好", "is_self": True, "time": "10:00"},
    {"mid": "2", "type": 1, "text": "周六有空吗？想约你去爬香山，早上八点出发，中午在山顶野餐", "is_self": False, "time": "10:01"},
    {"mid": "3", "type": 1, "text": "好啊！\n要带什么吗？", "is_self": True, "time": "10:02"},
    {"mid": "4", "type": 1, "text": "ok，周六见", "is_self": False, "time": "10:03"},
    {"mid": "5", "type": 1, "text": "对了记得穿外套，山顶风大", "is_self": True, "time": "10:04"},
    {"mid": "6", "type": 1, "text": "嗯嗯", "is_self": False, "time": "10:05"},
    {"mid": "7", "type": 1, "text": "这条消息比较长，用来测试多行气泡在滚动区域里的表现，应该会换行成两行显示", "is_self": True, "time": "10:06"},
]

view = QtWidgets.QListView()
view.resize(W, 560)
view.setModel(C.MessageModel())
view.model().set_messages(msgs, is_group=False)
view.setItemDelegate(C.MessageDelegate(view))
view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
view.setUniformItemSizes(False)
view.setMouseTracking(True)
view.setStyleSheet(f"background:{C.C_BG};border:0;")
view.show()
app.processEvents()


def grab_section(label):
    view.grab().save(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "data", "tmp", f"hover_{label}.png"))
    img = view.grab().toImage()
    return img


def diff_count(a, b):
    n = 0
    for y in range(min(a.height(), b.height())):
        for x in range(min(a.width(), b.width())):
            if a.pixel(x, y) != b.pixel(x, y):
                n += 1
    return n


# 初始状态
img_base = grab_section("base")

# 模拟鼠标移到第 2 行（长消息）
row2_center = view.visualRect(view.model().index(1, 0)).center()
QtGui.QCursor.setPos(row2_center)  # offscreen 无真正光标，改用 sendEvent
# 直接构造 QEnterEvent 发给 viewport
enter = QtGui.QEnterEvent(QtCore.QPointF(row2_center.x(), row2_center.y()),
                          QtCore.QPointF(0, 0), QtCore.QPointF(0, 0))
QtWidgets.QApplication.sendEvent(view.viewport(), enter)
app.processEvents()
img_hover = grab_section("hover_row2")

# 移出
leave = QtCore.QEvent(QtCore.QEvent.Type.Leave)
QtWidgets.QApplication.sendEvent(view.viewport(), leave)
app.processEvents()
img_leave = grab_section("leave")

print("像素差异:")
print(f"  base vs hover(第2行): {diff_count(img_base, img_hover)}")
print(f"  hover vs leave       : {diff_count(img_hover, img_leave)}")
print(f"  base vs leave        : {diff_count(img_base, img_leave)}")

# 找出差异区域 y 范围
def diff_rows(a, b):
    ys = set()
    for y in range(min(a.height(), b.height())):
        for x in range(min(a.width(), b.width())):
            if a.pixel(x, y) != b.pixel(x, y):
                ys.add(y)
                break
    return sorted(ys)

dr = diff_rows(img_base, img_hover)
print(f"base→hover 差异行: {dr}")
# 换算成消息行（每行高度不同，用 visualRect）
for i in range(view.model().rowCount()):
    r = view.visualRect(view.model().index(i, 0))
    print(f"  行{i}: y={r.y()} h={r.height()} text={msgs[i]['text'][:12]!r}")
