# -*- coding: utf-8 -*-
"""几何复检：气泡贴合内容 / 角标不压正文 / 文字不越界 / 气泡不压时间。
（复算 paint 的几何，断言不再有重叠。）"""
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

msgs = [
    ("短消息", "在吗？", False, None),
    ("短消息", "ok", True, None),
    ("长文本", "周六有空吗？想约你去爬香山，早上八点出发，中午在山顶野餐", False, None),
    ("有笔记短", "好啊！", True, True),
    ("有笔记多行", "好啊！我早就想去了。\n要带什么吗？", True, True),
    ("超长文本", "这是一条非常长的消息" * 8, False, None),
    ("空", "", True, None),
]

print(f"{'用例':10s} {'行高':>5s} {'气泡宽':>7s} {'文字区':>7s} {'角标压字':>8s} "
      f"{'气泡压时间':>10s} {'正文越界':>8s}")
print("-" * 76)

problems = []
for name, text, is_self, noted in msgs:
    m = C.MessageModel()
    m.set_messages([{"mid": "1", "text": text, "is_self": is_self,
                     "time": "2026-10-04 09:30:12"}], is_group=False)
    if noted:
        m.set_noted({"1"})
    view = QtWidgets.QListView()
    view.resize(W, 600)
    view.setModel(m)
    d = D(view)
    view.setItemDelegate(d)
    idx = m.index(0, 0)
    opt = QtWidgets.QStyleOptionViewItem()
    opt.widget = view
    opt.state = ST
    opt.rect = QtCore.QRect(0, 0, W, 600)
    size = d.sizeHint(opt, idx)

    # --- 复算 paint 几何（与实现一致）---
    has_note = bool(noted)
    max_w = min(d.MAX_W, W - 30)
    wrap_w = max_w - d.PAD_X * 2 - (d.BADGE_W if has_note else 0)
    n_lines, need_h = d._layout(text, max(wrap_w, d.PAD_X * 2))
    bubble_w = d._need_w(text, max_w, wrap_w, has_note)
    bh = max(32, need_h + d.PAD_Y * 2)
    text_avail_w = bubble_w - d.PAD_X * 2 - (d.BADGE_W if has_note else 0)
    row_h = size.height()
    time_h = d.TIME_H + d.TIME_GAP
    body_h = max(bh, row_h - time_h)
    x = (W - 14 - bubble_w) if is_self else 14
    y = max(2, (row_h - bh) // 2)
    if y + bh > body_h:
        y = max(2, body_h - bh)

    badge_rect = QtCore.QRect(x + bubble_w - d.BADGE_W, y + 2, d.BADGE_W, 12) if has_note else None
    text_rect = QtCore.QRect(x + d.PAD_X, y + d.PAD_Y, text_avail_w, bh - d.PAD_Y * 2)
    badge_hits = bool(badge_rect and badge_rect.intersects(text_rect))
    time_top = row_h - d.TIME_H
    bubble_hits_time = (y + bh) > time_top

    # 正文溢出检查（贴合渲染：长行会被 TextWordWrap 折行）：
    # 每个逻辑行按文字区宽折行后的总行数，必须 ≤ 文字区可容纳行数
    font = QtGui.QFont()
    font.setPointSize(d.FONT_SZ)
    fm = QtGui.QFontMetrics(font)
    line_h = d.LINE_H
    wrapped_rows = 0
    for ln in (text or "").split("\n"):
        if not ln:
            wrapped_rows += 1
            continue
        r = fm.boundingRect(0, 0, text_avail_w, 10000,
                            QtCore.Qt.TextFlag.TextWordWrap, ln)
        wrapped_rows += max(1, r.height() // line_h + (1 if r.height() % line_h else 0))
    capacity = max(1, (bh - d.PAD_Y * 2) // line_h)
    text_overflow = wrapped_rows > capacity

    print(f"{name:10s} {row_h:5d} {bubble_w:7d} {text_avail_w:7d} "
          f"{'是!' if badge_hits else '否':>8s} {'是!' if bubble_hits_time else '否':>10s} "
          f"{'是!' if text_overflow else '否':>8s}")

    if badge_hits:
        problems.append(f"{name}: 「笔记」角标与正文区域重叠")
    if bubble_hits_time:
        problems.append(f"{name}: 气泡底部越过时间带（{y+bh} > {time_top}）")
    if text_overflow:
        problems.append(f"{name}: 折行后正文超过文字区可容纳行数")

print()
if problems:
    print("FAIL %d 个问题：" % len(problems))
    for i, p in enumerate(problems, 1):
        print(f"  {i}. {p}")
    sys.exit(1)
print("ALL PASS: 气泡贴合内容 / 角标不压正文 / 文字不越界 / 不压时间带")
