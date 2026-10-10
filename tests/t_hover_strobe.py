# -*- coding: utf-8 -*-
"""高频抓帧：鼠标连续扫过多个气泡，每 10-20ms 截图一帧，捕捉瞬态闪烁/错位。
关注：时间文字是否在鼠标经过某行时短暂消失/错位/残影。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
import client as C  # noqa: E402

app = QtWidgets.QApplication([])

# 多样化的消息：不同高度、带时间
msgs = [
    {"mid": str(i), "type": 1,
     "text": ("短消息" if i % 3 == 0 else
              ("这是一条比较长的消息用来测试多行气泡在悬浮鼠标经过时的表现是否稳定不闪烁" if i % 3 == 1
               else "好啊！\n明天见\n记得带伞")),
     "is_self": i % 2 == 0,
     "time": f"2026-10-04 1{i%10}:0{i%10}:00"}
    for i in range(40)
]

win = QtWidgets.QWidget()
lay = QtWidgets.QVBoxLayout(win)
view = QtWidgets.QListView()
view.setObjectName("chat_scroll")
view.setStyleSheet(f"QListView{{background:{C.C_BG};border:0;outline:0;}}")
view.setModel(C.MessageModel())
view.model().set_messages(msgs, is_group=False)
view.setItemDelegate(C.MessageDelegate(view))
view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
view.setUniformItemSizes(False)
view.setMouseTracking(True)
lay.addWidget(view)
win.resize(740, 520)
win.show()
win.move(120, 60)
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)

vp = view.viewport()
# 窗口的全局坐标范围
tl = win.mapToGlobal(QtCore.QPoint(0, 0))
print("窗口全局:", tl.x(), tl.y(), win.width(), win.height())

frames_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "tmp", "frames")
os.makedirs(frames_dir, exist_ok=True)
for f in os.listdir(frames_dir):
    os.remove(os.path.join(frames_dir, f))

# 慢速扫过：从窗口左到右、从上到下 zigzag，每步截图
frames = []
t0 = time.time()
prev_img = None
changed_frames = 0
total = 0
for cy in range(80, 500, 14):      # 纵向
    for cx in range(60, 700, 80):  # 横向 zigzag
        QtGui.QCursor.setPos(tl.x() + cx, tl.y() + cy)
        time.sleep(0.012)
        for _ in range(2):
            app.processEvents()
        img = win.grab().toImage()
        total += 1
        if prev_img is not None:
            d = sum(1 for y in range(min(img.height(), prev_img.height()))
                    for x in range(min(img.width(), prev_img.width()))
                    if img.pixel(x, y) != prev_img.pixel(x, y))
            if d > 0:
                changed_frames += 1
                if changed_frames <= 4:
                    frames.append((d, prev_img, img, cx, cy))
        prev_img = img
dt = time.time() - t0
print(f"抓帧 {total} 次, 相邻帧有差异 {changed_frames} 次, 耗时 {dt:.0f}s")

# 分析差异区域（时间区域 vs 气泡区域）
print("\n差异帧详情:")
for d, a, b, cx, cy in frames:
    # 找出差异像素的 x/y 范围
    ys, xs = set(), set()
    for y in range(min(a.height(), b.height())):
        for x in range(min(a.width(), b.width())):
            if a.pixel(x, y) != b.pixel(x, y):
                ys.add(y); xs.add(x)
    print(f"  鼠标({cx},{cy}) 差异{d}px x=[{min(xs) if xs else '-'}..{max(xs) if xs else '-'}] "
          f"y=[{min(ys) if ys else '-'}..{max(ys) if ys else '-'}]")
    img_a = a
    img_a.save(os.path.join(frames_dir, f"diff_{cx}_{cy}_a.png"))
    b.save(os.path.join(frames_dir, f"diff_{cx}_{cy}_b.png"))

print(f"\n结论: {'PASS 相邻帧无差异, 无瞬态闪烁' if changed_frames == 0 else f'FAIL 发现 {changed_frames} 次瞬态变化'}")
win.close()