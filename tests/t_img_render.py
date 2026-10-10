# -*- coding: utf-8 -*-
"""桌面图片消息渲染测试：离屏绘制 type=3 消息，验证图片真的被画出来。
用合成 PNG 模拟微信 cache 明文图（测试文件写 F 盘 data/tmp）。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
import client as C  # noqa: E402

app = QtWidgets.QApplication([])
W = 820
ST = QtWidgets.QStyle.StateFlag.State_Enabled
D = C.MessageDelegate
BG = C.C_BG.lower()

TMP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "tmp")
os.makedirs(TMP, exist_ok=True)
img_path = os.path.join(TMP, "test_photo.png")

# 造一张 400x300 的纯红测试图
red = QtGui.QImage(400, 300, QtGui.QImage.Format.Format_RGB32)
red.fill(QtGui.QColor("#ff0000"))
red.save(img_path)

failures = []
def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f" | {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def make_model(msgs, resolver=None):
    m = C.MessageModel()
    m.set_messages(msgs, is_group=False)
    if resolver:
        m.set_image_resolver(resolver)
    return m


def render(model, row, d=None, view=None):
    view = view or QtWidgets.QListView()
    view.resize(W, 800)
    view.setModel(model)
    d = d or D(view)
    view.setItemDelegate(d)
    idx = model.index(row, 0)
    opt = QtWidgets.QStyleOptionViewItem()
    opt.widget = view
    opt.state = ST
    opt.rect = QtCore.QRect(0, 0, W, 800)
    size = d.sizeHint(opt, idx)
    img = QtGui.QImage(W, size.height() + 30, QtGui.QImage.Format.Format_RGB32)
    img.fill(QtGui.QColor(C.C_BG))
    p = QtGui.QPainter(img)
    opt.rect = QtCore.QRect(0, 0, W, size.height())
    d.paint(p, opt, idx)
    p.end()
    return img, size


print("== 1) 图片消息能解析并渲染 ==")
msgs = [
    {"mid": "img1", "type": 3, "text": "", "is_self": False,
     "media": {"md5": "deadbeef"}, "time": "2026-10-04 10:00:00"},
    {"mid": "txt1", "type": 1, "text": "你好", "is_self": True, "time": "2026-10-04 10:01:00"},
]
m = make_model(msgs, resolver=lambda md5: img_path if md5 == "deadbeef" else None)
pm = m.pixmap_for("img1", "deadbeef")
check("pixmap 加载成功", pm is not None and not pm.isNull())
check("pixmap 尺寸正确(400x300)", pm.width() == 400 and pm.height() == 300)

img, size = render(m, 0)
# 检查红色像素（图片被画出来了）
red_px = 0
for y in range(img.height()):
    for x in range(img.width()):
        if QtGui.QColor(img.pixel(x, y)).name() == "#ff0000":
            red_px += 1
print(f"  图片行高={size.height()} 红色像素={red_px}")
check("图片被画出（有红色像素）", red_px > 1000, f"仅 {red_px}")

# 图片行应比普通文字行高
_, size_txt = render(m, 1)
print(f"  文字行高={size_txt.height()}")
check("图片行高 > 文字行高", size.height() > size_txt.height(),
      f"{size.height()} vs {size_txt.height()}")

print("\n== 2) 无缓存图时显示占位 ==")
msgs2 = [{"mid": "img2", "type": 3, "text": "", "is_self": True,
          "media": {"md5": "nope"}, "time": "2026-10-04 10:02:00"}]
m2 = make_model(msgs2, resolver=lambda md5: None)
img2, size2 = render(m2, 0)
# 占位应该有文字像素（非背景非气泡色）
dark_px = 0
for y in range(size2.height()):
    for x in range(img2.width()):
        c = QtGui.QColor(img2.pixel(x, y)).name().lower()
        if c not in (BG, "#ffffff", "#d9dde3"):
            dark_px += 1
print(f"  占位行高={size2.height()} 深色像素={dark_px}")
check("无图时显示占位文字", dark_px > 100, f"仅 {dark_px}")

print("\n== 3) 没有 resolver 时不崩 ==")
m3 = make_model(msgs2)  # 无 resolver
img3, size3 = render(m3, 0)
check("无 resolver 渲染不崩", img3.width() > 0)

print("\n== 4) bytes 解析器（模拟 wxgf→jpeg 转换） ==")
# 用 PIL 把红图转成 bytes，模拟 load_displayable_image 的返回
from PIL import Image
import io as _io
buf = _io.BytesIO()
Image.frombytes("RGB", (400, 300), b"\xff\x00\x00" * (400 * 300)).save(buf, "JPEG")
jpg_bytes = buf.getvalue()
m4 = make_model(msgs, resolver=None)
m4.set_image_bytes_resolver(lambda md5: jpg_bytes if md5 == "deadbeef" else None)
pm4 = m4.pixmap_for("img1", "deadbeef")
check("bytes 解析器加载成功", pm4 is not None and not pm4.isNull())
check("bytes 图尺寸正确", pm4.width() == 400 and pm4.height() == 300)
img4, size4 = render(m4, 0)
red4 = sum(1 for y in range(img4.height()) for x in range(img4.width())
           if QtGui.QColor(img4.pixel(x, y)).red() > 200
           and QtGui.QColor(img4.pixel(x, y)).green() < 80
           and QtGui.QColor(img4.pixel(x, y)).blue() < 80)
check("bytes 图被画出", red4 > 1000, f"仅 {red4}")

print("\n== 5) wxgf 无法解码时返回 None（占位兜底） ==")
m5 = make_model(msgs, resolver=None)
m5.set_image_bytes_resolver(lambda md5: None)  # 模拟 wxgf 转换失败
pm5 = m5.pixmap_for("img1", "deadbeef")
check("wxgf 无字节 → 不崩", pm5 is None)
img5, size5 = render(m5, 0)
check("wxgf 占位渲染不崩", img5.width() > 0)

print()
for f in failures:
    print("FAIL:", f)
if failures:
    sys.exit(1)
print("ALL PASS: 桌面图片消息渲染正常")
