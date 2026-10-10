"""离屏渲染验证：有笔记 / 无笔记 两种气泡的像素颜色确实不同，删笔记后恢复原色。
不启动真实微信数据、不写 C 盘。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

import client as C  # noqa: E402

app = QtWidgets.QApplication([])

BASE = C.MessageDelegate.C_SELF_BG if hasattr(C.MessageDelegate, "C_SELF_BG") else None


def make_model():
    m = C.MessageModel()
    m.set_messages([
        {"mid": "a1", "text": "普通消息", "is_self": True, "time": "10:00"},
        {"mid": "a2", "text": "写了笔记的消息", "is_self": True, "time": "10:01"},
        {"mid": "a3", "text": "对方普通消息", "is_self": False, "time": "10:02"},
        {"mid": "a4", "text": "对方写了笔记", "is_self": False, "time": "10:03"},
    ], is_group=False)
    return m


def render(model, row):
    view = QtWidgets.QListView()
    view.setModel(model)
    d = C.MessageDelegate(view)
    view.setItemDelegate(d)
    idx = model.index(row, 0)
    opt = QtWidgets.QStyleOptionViewItem()
    opt.rect = QtCore.QRect(0, 0, 900, 60)
    opt.state = QtWidgets.QStyle.StateFlag.State_Enabled
    size = d.sizeHint(opt, idx)
    if size.width() < opt.rect.width():
        size.setWidth(opt.rect.width())
    img = QtGui.QImage(size.width() + 20, size.height() + 20,
                       QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(C.C_BG))
    p = QtGui.QPainter(img)
    opt.rect = QtCore.QRect(10, 10, size.width(), size.height())
    d.paint(p, opt, idx)
    p.end()
    return img


def pixel(img, x, y):
    return QtGui.QColor(img.pixel(x, y)).name()


def bubble_color(img):
    """在气泡区域内扫描，找出现次数最多的非背景颜色 = 气泡填充色。"""
    counts = {}
    for y in range(10, img.height() - 10, 3):
        for x in range(10, img.width() - 10, 3):
            c = QtGui.QColor(img.pixel(x, y)).name()
            if c.lower() == C.C_BG.lower():
                continue
            counts[c] = counts.get(c, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


# 1) 全部无笔记 —— 记录原始颜色
m = make_model()
m.set_noted(set())
before_self = bubble_color(render(m, 0))
before_peer = bubble_color(render(m, 2))
print("无笔记 · 自己发的气泡色 :", before_self)
print("无笔记 · 对方发的气泡色 :", before_peer)

# 2) 标记 a2 / a4 有笔记 —— 颜色必须变
m.set_noted({"a2", "a4"})
note_self = bubble_color(render(m, 1))
note_peer = bubble_color(render(m, 3))
print("有笔记 · 自己发的气泡色 :", note_self)
print("有笔记 · 对方发的气泡色 :", note_peer)

# 3) 删除笔记 —— 必须恢复原色
m.set_noted(set())
after_self = bubble_color(render(m, 0))
after_peer = bubble_color(render(m, 2))
print("删笔记后 · 自己发的气泡色 :", after_self)
print("删笔记后 · 对方发的气泡色 :", after_peer)

ok = True


def check(name, cond):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + name)
    ok = ok and cond


print("\n断言：")
check("有笔记后自己发的气泡变色", note_self.lower() != before_self.lower())
check("有笔记后对方发的气泡变色", note_peer.lower() != before_peer.lower())
check("自己发的笔记色 == C_NOTE_SELF", note_self.lower() == C.MessageDelegate.C_NOTE_SELF.lower())
check("对方发的笔记色 == C_NOTE_PEER", note_peer.lower() == C.MessageDelegate.C_NOTE_PEER.lower())
check("删除笔记后自己发的恢复原色", after_self.lower() == before_self.lower())
check("删除笔记后对方发的恢复原色", after_peer.lower() == before_peer.lower())

# 标记 a1 后：a1 变笔记色，但未标记的 a2（同模型另一行）保持原色
m2 = make_model()
m2.set_noted({"a1"})
c_a1_marked = bubble_color(render(m2, 0))
c_a2_untouched = bubble_color(render(m2, 1))
m2.set_noted(set())
c_a1_restored = bubble_color(render(m2, 0))
check("标记的行变笔记色", c_a1_marked.lower() == C.MessageDelegate.C_NOTE_SELF.lower())
check("未标记的行颜色不受影响", c_a2_untouched.lower() == before_self.lower())
check("取消标记后恢复原色", c_a1_restored.lower() == before_self.lower())

print("\n" + ("ALL PASS: 笔记变色 / 删笔记恢复原色 渲染正确" if ok else "FAIL: 渲染不符合预期"))
sys.exit(0 if ok else 1)
