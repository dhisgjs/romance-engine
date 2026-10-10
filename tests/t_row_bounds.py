# -*- coding: utf-8 -*-
"""回归：所有行高下，时间文字都不得画到 item.rect 之外。
越界会让 Qt 的局部重绘裁掉/串行，直接表现为鼠标移入移出时「时间忽隐忽现」。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
import client as C  # noqa: E402

app = QtWidgets.QApplication([])
W = 820
BG = C.C_BG.lower()
ST = QtWidgets.QStyle.StateFlag.State_Enabled

CASES = [
    ("单行短消息", "你好", True),
    ("单行长消息", "这是一条比较长的消息用来测试气泡宽度和换行效果" * 3, True),
    ("单行短消息(对方)", "在吗", False),
    ("单行长消息(对方)", "对方发来的一条很长的消息需要换行显示测试排版" * 3, False),
    ("多行含换行", "第一行\n第二行\n第三行\n第四行", False),
    ("空文本", "", True),
]

bad = []
for name, text, is_self in CASES:
    m = C.MessageModel()
    m.set_messages([{"mid": "x", "text": text, "is_self": is_self,
                     "time": "2026-10-04 10:23:45"}], is_group=False)
    view = QtWidgets.QListView()
    view.resize(W, 400)
    view.setModel(m)
    d = C.MessageDelegate(view)
    view.setItemDelegate(d)
    idx = m.index(0, 0)
    opt = QtWidgets.QStyleOptionViewItem()
    opt.widget = view
    opt.state = ST
    opt.rect = QtCore.QRect(0, 0, W, 400)
    size = d.sizeHint(opt, idx)

    img = QtGui.QImage(W, size.height() + 30, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(C.C_BG))
    p = QtGui.QPainter(img)
    opt.rect = QtCore.QRect(0, 0, W, size.height())
    d.paint(p, opt, idx)
    p.end()

    last_y = -1
    for y in range(img.height()):
        for x in range(img.width()):
            if QtGui.QColor(img.pixel(x, y)).name().lower() != BG:
                last_y = y
                break
    overflow = last_y >= size.height()
    # 气泡和时间不能重叠（时间带起点 = 高度 - TIME_H - 留白）
    print(f"  {name:22s} 行高={size.height():4d} 末像素 y={last_y:4d} "
          f"{'越界!' if overflow else 'OK'}")
    if overflow:
        bad.append(name)

print()
if bad:
    print("FAIL 有内容画出行外:", bad)
    sys.exit(1)
print("ALL PASS: 各种行高下内容都完全在 item 内 —— hover 局部重绘不会再裁掉时间")
