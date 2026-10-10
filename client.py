# -*- coding: utf-8 -*-
"""微信聊天记录桌面客户端（PySide6）—— 深色现代炫酷界面。

独立 exe：启动时自动完成 找微信→数据目录→提取密钥→解密→浏览，
后台实时监视 -wal 增量，微信收到/发出新消息时自动刷新当前聊天。

数据目录默认放 exe 旁边 data/，不写系统盘。全部逻辑只读微信文件。
"""
from __future__ import annotations

import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False):
    APP_ROOT = os.path.dirname(sys.executable)  # 打包后数据目录放 exe 旁边
else:
    APP_ROOT = _HERE
sys.path.insert(0, APP_ROOT)

from PySide6 import QtCore, QtGui, QtWidgets

from backend.core import memscan, pipeline
from backend.core.aigen import AIClient, test_connection, PRESET_MODELS, friendly_error
from backend.core import buddy_memory
from backend.core.exporter import _ts
from backend.core.models import Store
from backend.core import notes as notes_mod
from backend.core import ai_chats
from backend.core import account_info
from backend.core.watcher import ChatWatcher

APP_NAME = "微聊助手"
DATA_DIR = os.path.join(APP_ROOT, "data")
DECRYPTED_DIR = os.path.join(DATA_DIR, "decrypted")
KEYS_DIR = os.path.join(DATA_DIR, "keys")
os.makedirs(DECRYPTED_DIR, exist_ok=True)
os.makedirs(KEYS_DIR, exist_ok=True)
notes_mod.init(os.path.join(DATA_DIR, "notes.json"))
buddy_memory.init(os.path.join(DATA_DIR, "buddy_memory.json"))
ai_chats.init(os.path.join(DATA_DIR, "ai_chats.json"))

# ---------------------------------------------------------------- 主题（明亮清爽 · 微信风）
C_BG        = "#f4f7f5"   # 窗口底（浅灰，像微信）
C_BG_2      = "#ffffff"   # 面板底（白）
C_BG_3      = "#f7faf8"   # 悬浮 / 次级面板（极浅灰）
C_BORDER    = "#e2e9e5"   # 边框（浅）
C_ACCENT    = "#07c160"   # 微信绿
C_ACCENT_2  = "#34d17c"
C_GREEN_DK  = "#059e50"
C_TEXT      = "#1f2329"   # 主文字（深灰黑）
C_TEXT_DIM  = "#8a9099"   # 次要文字（灰）
C_SELF_BG   = "#95ec69"   # 自发气泡（微信浅绿）
C_SELF_BG2  = "#a9f281"
C_PEER_BG   = "#ffffff"   # 对方气泡（白）
C_SYS       = "#f2f3f5"

# 全局样式表
QSS = f"""
* {{ font-family: "Microsoft YaHei UI","Microsoft YaHei","Segoe UI",sans-serif; }}
QMainWindow, QWidget#root {{ background: {C_BG}; color: {C_TEXT}; }}
QWidget#topbar {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #056b43, stop:0.5 #078f52, stop:1 #056b43);
                  border-bottom: 1px solid #075d3b; }}
QLabel#app_title {{ color: #fff; font-size: 18px; font-weight: 700; }}
QLabel#acc_label {{ color: rgba(255,255,255,.85); font-size: 12.5px; }}
QLabel#status_label {{ color: rgba(255,255,255,.85); font-size: 12.5px; }}
QPushButton#btn_extract {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {C_ACCENT_2}, stop:1 {C_ACCENT});
    color:#fff; border:0; border-radius:8px; padding:7px 18px; font-weight:600;
}}
QPushButton#btn_extract:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #44dc87, stop:1 {C_ACCENT}); }}
QPushButton#btn_extract:pressed {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #04a04e, stop:1 #06b556); }}
QPushButton#btn_extract:disabled {{ background:#c8d6cc; color:#fff; }}
/* 所有按钮：明显的按下反馈 */
QPushButton#btn_extract:pressed {{ border: 2px solid #d9ffe8; }}
QPushButton:disabled {{ color:#b0b5bd; }}
QProgressBar#bar {{
    background:#e6e8eb; border:0; border-radius:5px; height:10px;
}}
QProgressBar#bar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {C_ACCENT}, stop:1 #59f7b0);
                            border-radius:5px; }}
QListView#contact_list {{ background: {C_BG_2}; border:0; outline:0; }}
QListView#contact_list::item {{ border:0; border-radius:7px; margin:3px 6px; padding:4px 6px; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background:#cbd8d1; border-radius:4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background:#9fb9aa; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea#chat_scroll {{ background: {C_BG}; border:0; }}
QWidget#chat_holder {{ background: {C_BG}; }}
QStatusBar {{ background: {C_BG_2}; color: {C_TEXT_DIM}; border-top:1px solid {C_BORDER}; padding:3px 8px; }}
QToolTip {{ background:#ffffff; color:{C_TEXT}; border:1px solid {C_BORDER}; border-radius:6px; padding:5px 8px; }}
QSplitter::handle {{ background: #dce7e1; width: 4px; }}
"""

AVATAR_COLORS = [
    ("#07c160", "#3ddc84"), ("#4f8cff", "#7ab2ff"), ("#ff7a45", "#ffb98a"),
    ("#a66fff", "#d0a8ff"), ("#f5a623", "#ffd07a"), ("#ff5e7a", "#ffa3b5"),
    ("#12b8c4", "#7ce6ec"), ("#f759ab", "#ffb1dd"),
]


def avatar_gradient(username: str):
    """按用户名哈希取一组渐变色。"""
    h = 0
    for ch in username:
        h = (h * 131 + ord(ch)) & 0xFFFF
    return AVATAR_COLORS[h % len(AVATAR_COLORS)]


def make_gradient(c1: str, c2: str):
    g = QtGui.QLinearGradient(0, 0, 0, 1)
    g.setColorAt(0, QtGui.QColor(c1))
    g.setColorAt(1, QtGui.QColor(c2))
    return g


# ---------------------------------------------------------------- 信号 / 提取线程


def _ago_text(mtime: float) -> str:
    """把时间戳说成「刚刚 / 3 小时前 / 2 天前」这类人话。"""
    import time as _t
    d = max(0.0, _t.time() - float(mtime or 0))
    if d < 60:
        return "刚刚"
    if d < 3600:
        return "%d 分钟前" % int(d // 60)
    if d < 86400:
        return "%d 小时前" % int(d // 3600)
    if d < 86400 * 30:
        return "%d 天前" % int(d // 86400)
    return _t.strftime("%Y-%m-%d", _t.localtime(float(mtime)))

class WorkerSignals(QtCore.QObject):
    log = QtCore.Signal(str)
    progress = QtCore.Signal(int)
    done = QtCore.Signal(dict)
    error = QtCore.Signal(str)


class ExtractWorker(QtCore.QThread):
    def __init__(self, account, data_dir, parent=None):
        super().__init__(parent)
        self.account = account
        self.data_dir = data_dir
        self.sig = WorkerSignals()

    def run(self):
        try:
            res = pipeline.run_extract(
                self.account, self.data_dir, DECRYPTED_DIR, KEYS_DIR,
                log=lambda m: self.sig.log.emit(m),
                progress=lambda p: self.sig.progress.emit(p))
            self.sig.done.emit(res)
        except Exception as e:
            self.sig.error.emit(str(e))


# ---------------------------------------------------------------- 联系人列表（虚拟化）

class ContactModel(QtCore.QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[tuple[str, str, int]] = []

    def set_items(self, items):
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._items)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        u, d, c = self._items[index.row()]
        if role == QtCore.Qt.ItemDataRole.UserRole:
            return u
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return d
        if role == QtCore.Qt.ItemDataRole.UserRole + 1:
            return c
        return None

    def talker_at(self, row):
        return self._items[row][0] if 0 <= row < len(self._items) else None


class ContactDelegate(QtWidgets.QStyledItemDelegate):
    """深色虚拟化联系人行：渐变头像 + 名称 + 微信号 + 条数徽章。"""

    def paint(self, painter, option, index):
        u = index.data(QtCore.Qt.ItemDataRole.UserRole) or ""
        d = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        c = index.data(QtCore.Qt.ItemDataRole.UserRole + 1) or 0
        rect = option.rect
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        # 选中/悬浮背景（微信风浅色）
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, QtGui.QColor("#e6f7ec"))
            painter.fillRect(rect.adjusted(0, 0, -3, 0), QtGui.QColor("#e6f7ec"))
        elif option.state & QtWidgets.QStyle.StateFlag.State_MouseOver:
            painter.fillRect(rect, QtGui.QColor("#f7f8fa"))
        else:
            painter.fillRect(rect, QtGui.QColor(C_BG_2))
        # 左侧高亮条
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(C_ACCENT))
            painter.drawRoundedRect(QtCore.QRect(rect.left() + 2, rect.top() + 12, 4, rect.height() - 24), 2, 2)

        # 渐变头像
        c1, c2 = avatar_gradient(u)
        av = QtCore.QRect(rect.left() + 12, rect.top() + 8, 36, 36)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(make_gradient(c1, c2))
        painter.drawEllipse(av)
        painter.setPen(QtGui.QColor("#ffffff"))
        f = painter.font()
        f.setPointSize(11)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(av, QtCore.Qt.AlignmentFlag.AlignCenter, d[:1] or "?")

        # 名称（选中加粗）
        f2 = painter.font()
        f2.setPointSize(10.5)
        f2.setBold(bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected))
        painter.setFont(f2)
        painter.setPen(QtGui.QColor(C_TEXT))
        tr = QtCore.QRect(rect.left() + 58, rect.top() + 8, rect.width() - 140, 22)
        painter.drawText(tr, QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.TextFlag.TextSingleLine,
                         painter.fontMetrics().elidedText(d, QtCore.Qt.TextElideMode.ElideRight, tr.width()))

        # 微信号
        f3 = painter.font()
        f3.setPointSize(8)
        f3.setBold(False)
        painter.setFont(f3)
        painter.setPen(QtGui.QColor(C_TEXT_DIM))
        tr2 = QtCore.QRect(rect.left() + 58, rect.top() + 26, rect.width() - 140, 18)
        painter.drawText(tr2, QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.TextFlag.TextSingleLine,
                         painter.fontMetrics().elidedText(u, QtCore.Qt.TextElideMode.ElideRight, tr2.width()))

        # 条数徽章
        if c > 0:
            badge = QtCore.QRect(rect.right() - 66, rect.top() + 16, 54, 20)
            painter.setBrush(QtGui.QColor("#e6f7ec" if not (option.state & QtWidgets.QStyle.StateFlag.State_Selected) else "#d3f0e0"))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge, 10, 10)
            painter.setPen(QtGui.QColor(C_ACCENT))
            f4 = painter.font()
            f4.setPointSize(8.5)
            f4.setBold(True)
            painter.setFont(f4)
            painter.drawText(badge, QtCore.Qt.AlignmentFlag.AlignCenter, f"{c}")
        painter.restore()

    def sizeHint(self, option, index):
        return QtCore.QSize(0, 54)



# ---------------------------------------------------------------- 消息虚拟列表
class MessageModel(QtCore.QAbstractListModel):
    """聊天消息模型：只存数据（几万条也没关系），由 delegate 只画可见行。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._msgs: list[dict] = []
        self.is_group = False
        self._noted: set[str] = set()   # 写了笔记的 mid，用于变色高亮
        self._resolve_img = None        # resolve_cache_image(md5) -> 明文图路径
        self._resolve_bytes = None      # load_displayable_image(md5) -> 可显示字节（hevc已转）
        self._pix_cache: dict[str, QtGui.QPixmap] = {}
    def set_image_resolver(self, fn):
        """注入图片定位回调：fn(md5) -> 缓存明文图路径 or None。"""
        self._resolve_img = fn
        self._resolve_bytes = None
        self._pix_cache.clear()
    def set_image_bytes_resolver(self, fn):
        """注入图片字节回调：fn(md5) -> 可直接解码的字节（wxgf 已转 JPEG）。"""
        self._resolve_bytes = fn
        self._resolve_img = None
        self._pix_cache.clear()
    def clear_image_cache(self):
        self._pix_cache.clear()
    def pixmap_for(self, mid: str, md5: str):
        """懒加载并缓存图片 QPixmap（type=3 消息的 cache 明文图）。"""
        if not md5:
            return None
        if mid in self._pix_cache:
            return self._pix_cache.get(mid)
        try:
            if self._resolve_bytes is not None:
                data = self._resolve_bytes(md5)
                if not data:
                    self._pix_cache[mid] = None
                    return None
                pm = QtGui.QPixmap()
                if not pm.loadFromData(data):
                    self._pix_cache[mid] = None
                    return None
                self._pix_cache[mid] = pm
                return pm
            if self._resolve_img is None:
                return None
            path = self._resolve_img(md5)
            if not path:
                self._pix_cache[mid] = None
                return None
            pm = QtGui.QPixmap(path)
            if pm.isNull():
                self._pix_cache[mid] = None
                return None
            self._pix_cache[mid] = pm
            return pm
        except Exception:
            return None
    def set_messages(self, msgs: list, is_group: bool):
        self.beginResetModel()
        self._msgs = msgs
        self.is_group = is_group
        self.endResetModel()
    def set_noted(self, mids: set[str]):
        """标记哪些消息有笔记（决定气泡配色）。"""
        if mids == self._noted:
            return
        changed = [i for i, m in enumerate(self._msgs) if m.get("mid") in mids]
        old = self._noted
        self._noted = mids
        if not changed:
            # 也可能有笔记被删掉的行
            changed = [i for i, m in enumerate(self._msgs) if m.get("mid") in old]
        for i in changed:
            idx = self.index(i, 0)
            self.dataChanged.emit(idx, idx, [QtCore.Qt.ItemDataRole.UserRole])
    def refresh_all(self):
        if self._msgs:
            self.dataChanged.emit(self.index(0, 0),
                                   self.index(len(self._msgs) - 1, 0),
                                   [QtCore.Qt.ItemDataRole.UserRole])
    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._msgs)
    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._msgs)):
            return None
        m = self._msgs[index.row()]
        if role == QtCore.Qt.ItemDataRole.UserRole:
            if m.get("mid") in self._noted:
                return {**m, "has_note": True}
            return m
        return None
class ChatListView(QtWidgets.QListView):
    """聊天列表：每次重绘前先清整块视口，避免局部重绘残留上一帧像素。

    Qt 在鼠标悬停/选中变化时只重绘受影响行的小矩形，若该矩形与 delegate
    画的范围不完全吻合，上一帧像素就会残留，看起来像"鼠标移入移出时
    气泡和时间闪烁错位"。这里在 super().paintEvent 之前把整个 viewport 刷成
    聊天底色，任何残留都不可能发生。
    """

    def paintEvent(self, ev):
        p = QtGui.QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QtGui.QColor(C_BG))
        p.end()
        super().paintEvent(ev)


class MessageDelegate(QtWidgets.QStyledItemDelegate):
    """消息气泡绘制：自发绿右、对方深左、时间、多行文字自适应高度（微信风格）。"""

    MAX_W = 520          # 气泡最大宽度
    PAD_X = 14           # 文字水平内边距
    PAD_Y = 9            # 文字垂直内边距
    LINE_H = 22          # 行高（含行距）
    FONT_SZ = 13         # 正文字号
    GAP = 10             # 相邻消息气泡的垂直间距（微信风格，不连在一起）
    TIME_H = 13          # 时间文字高度（px）
    TIME_GAP = 3         # 气泡底到时间文字顶的距离（px）
    BADGE_W = 46         # 右上角「笔记」角标占用宽度（有笔记时正文右侧内缩，避免盖字）
    TOP_PAD = 4          # 气泡顶部到行顶的间距（顶部对齐，hover 重绘不跳动）
    # 正文右侧安全余量：horizontalAdvance 不含末字字形右缘，宽度取等时末字会被裁掉
    TEXT_PAD_R = 2

    # 图片消息（type=3，微信 cache 明文图）
    IMG_MAX_W = 260      # 图片最大显示宽度
    IMG_MAX_H = 340      # 图片最大显示高度
    IMG_MIN_H = 60       # 图片最小显示高度（防止占位图过高）

    # 有笔记的消息用醒目配色（区别于普通气泡）
    C_NOTE_SELF = "#ffd666"   # 自己发的（琥珀黄）
    C_NOTE_PEER = "#fff3cd"   # 对方发的（浅黄）
    C_NOTE_BAR = "#f5a623"    # 左侧标记条
    C_NOTE_TEXT = "#6b4e00"  # 深棕字，保证对比度

    def _need_w(self, text: str, max_w: int, wrap_w: int, has_note: bool) -> int:
        """气泡宽度：单行贴合文字（含角标预留），任一段需换行则占满 max_w。"""
        if not text:
            w = self.PAD_X * 2
        else:
            font = QtGui.QFont()
            font.setPointSize(self.FONT_SZ)
            fm = QtGui.QFontMetrics(font)
            worst = 0
            for ln in text.split("\n"):
                if not ln:
                    continue
                aw = fm.horizontalAdvance(ln)
                if aw > wrap_w:
                    return max_w   # 该段在文字区内容不下 → 换行，气泡满宽
                worst = max(worst, aw)
            # +TEXT_PAD_R：末字字形右缘可能超出 advance，取等宽会把最后一个字裁掉
            w = worst + self.PAD_X * 2 + self.TEXT_PAD_R
        if has_note:
            w = max(w, self.PAD_X * 2 + 26)   # 角标最小宽度
            w += self.BADGE_W                 # 右侧预留「笔记」角标空间
        return min(max_w, w)

    def _layout(self, text: str, avail_w: int):
        """按 avail_w 用 QFontMetrics.boundingRect 精确计算 wrap 后的高度（不截断）。"""
        if not text:
            return 1, self.LINE_H
        font = QtGui.QFont()
        font.setPointSize(self.FONT_SZ)
        fm = QtGui.QFontMetrics(font)
        total = 0
        for ln in text.split("\n"):
            if not ln:
                total += 1
                continue
            rect = fm.boundingRect(0, 0, avail_w, 10000,
                                   QtCore.Qt.TextFlag.TextWordWrap, ln)
            total += max(1, rect.height() // self.LINE_H + (1 if rect.height() % self.LINE_H else 0))
        return total, total * self.LINE_H

    def _img_display(self, pm, max_w):
        """按图片纵横比 + 最大宽高约束，计算要显示的 (w, h)。"""
        w, h = pm.width(), pm.height()
        if w <= 0 or h <= 0:
            return self.IMG_MAX_W, self.IMG_MAX_H  # 未知尺寸，用默认框
        # 大图缩小到上限内；小图最多放大到上限（但避免过度放大糊）
        scale = min(self.IMG_MAX_W / w, self.IMG_MAX_H / h)
        if w > self.IMG_MAX_W or h > self.IMG_MAX_H:
            scale = min(scale, 1.0)
        else:
            scale = min(scale, 2.0)  # 小图最多放大 2 倍
        return max(24, int(w * scale)), max(24, int(h * scale))

    def _image_draw(self, painter, rect, pm):
        """在 bubble 矩形内画图（等比缩放、圆角裁剪）。"""
        pw, ph = self._img_display(pm, rect.width())
        draw = QtCore.QRect(rect.left() + self.PAD_X, rect.top() + self.PAD_Y,
                            pw, ph)
        # 等比缩放绘制
        painter.save()
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor("#d9dde3"))
        painter.drawRoundedRect(draw, 6, 6)
        if pw <= 0 or ph <= 0:
            painter.restore()
            return
        try:
            scaled = pm.scaled(draw.width(), draw.height(),
                               QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                               QtCore.Qt.TransformationMode.SmoothTransformation)
        except Exception:
            painter.restore()
            return
        # 居中
        x = draw.left() + (draw.width() - scaled.width()) // 2
        y = draw.top() + (draw.height() - scaled.height()) // 2
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(QtCore.QRectF(draw), 6, 6)
        painter.save()
        painter.setClipPath(clip)
        painter.drawPixmap(QtCore.QPoint(x, y), scaled)
        painter.restore()
        painter.restore()

    def paint(self, painter, option, index):
        m = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not m:
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = option.rect
        # 先整体铺背景：局部重绘（hover/选中）不会残留邻行内容
        painter.fillRect(r, QtGui.QColor(C_BG))
        is_self = bool(m.get("is_self"))
        has_note = bool(m.get("has_note"))
        text = m.get("text") or ""
        font = QtGui.QFont()
        font.setPointSize(self.FONT_SZ)
        painter.setFont(font)
        fm = painter.fontMetrics()

        # ----- 图片消息（type=3，微信 cache 明文图）-----
        media = m.get("media") or {}
        is_img = (m.get("type") == 3 and media.get("md5"))
        pm = None
        img_w = img_h = 0
        if is_img:
            mid = m.get("mid") or ""
            pm = index.model().pixmap_for(mid, media["md5"]) if index.model() else None
            img_w = self.IMG_MAX_W
            img_h = self.IMG_MAX_H
            if pm is not None:
                img_w, img_h = self._img_display(pm, self.IMG_MAX_W)
            # 图片气泡宽度贴合图片
            bubble_w = img_w + self.PAD_X * 2
            max_w = min(self.MAX_W, r.width() - 30)
            bubble_w = min(bubble_w, max_w)
        else:
            # 气泡宽度：单行贴合文字，任一段需换行则占满可用宽（微信风格）
            # 有笔记时给右上角角标预留宽度，防止角标压住正文
            max_w = min(self.MAX_W, r.width() - 30)
            wrap_w = max_w - self.PAD_X * 2 - (self.BADGE_W if has_note else 0)
            n_lines, need_h = self._layout(text, max(wrap_w, self.PAD_X * 2))
            bubble_w = self._need_w(text, max_w, wrap_w, has_note)
            text_avail_w = bubble_w - self.PAD_X * 2 - self.TEXT_PAD_R \
                - (self.BADGE_W if has_note else 0)

        # 气泡高度：图片按图高；文字按行数
        if is_img:
            bh = max(32, img_h + self.PAD_Y * 2)
        else:
            bh = max(32, need_h + self.PAD_Y * 2)

        # 气泡位置：顶部对齐（只用 r.top()，对 Qt 缓存行高误差免疫 → hover 重绘不跳动）
        # 自发靠右，对方靠左；时间紧随气泡下方，整体随行高向下排布
        row_h = r.height()
        time_h = self.TIME_H + self.TIME_GAP
        if is_self:
            x = r.right() - 14 - bubble_w
        else:
            x = r.left() + 14
        y = r.top() + self.TOP_PAD
        bubble = QtCore.QRect(x, y, bubble_w, bh)
        # 时间带：紧贴气泡底部；若行高不够（Qt 给了偏小的高度）则贴行底
        t_y = bubble.bottom() + self.TIME_GAP
        if t_y + self.TIME_H > r.bottom():
            t_y = max(r.top(), r.bottom() - self.TIME_H)

        # 画气泡（微信式：圆角、小尾巴角）；有笔记的换醒目配色
        if has_note:
            painter.setBrush(QtGui.QColor(self.C_NOTE_SELF if is_self else self.C_NOTE_PEER))
        elif is_self:
            painter.setBrush(QtGui.QColor(C_SELF_BG))
        else:
            painter.setBrush(QtGui.QColor(C_PEER_BG))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bubble, 10, 10)

        # 有笔记：左侧一条竖向标记条 + 右上角「笔记」角标（角标区与正文互不重叠）
        if has_note:
            bar = QtCore.QRectF(bubble.left() + 2.5, bubble.top() + 6, 3, bubble.height() - 12)
            painter.setBrush(QtGui.QColor(self.C_NOTE_BAR))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bar, 1.5, 1.5)
            f = QtGui.QFont()
            f.setPointSize(7)
            painter.setFont(f)
            painter.setPen(QtGui.QColor(self.C_NOTE_BAR))
            painter.drawText(QtCore.QRect(bubble.right() - self.BADGE_W, bubble.top() + 2,
                                          self.BADGE_W - 4, 12),
                             QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.TextFlag.TextSingleLine,
                             "📝 笔记")

        # 内容：图片消息画图，文字消息画字
        if is_img:
            if pm is not None:
                self._image_draw(painter, bubble, pm)
            else:
                # 无图：画占位（可能微信没缓存明文，或还没打开过）
                painter.setPen(QtGui.QColor("#b6bcc6"))
                painter.setFont(QtGui.QFont())
                tr2 = bubble.adjusted(self.PAD_X, self.PAD_Y, -self.PAD_X, -self.PAD_Y)
                painter.drawText(tr2, QtCore.Qt.AlignmentFlag.AlignCenter,
                                 "🖼 [图片未在微信中打开过]\n请先在微信里点开这张图片")
        else:
            # 文字：左上角内边距开始，wordwrap（浅色主题：深色文字）
            painter.setPen(QtGui.QColor(self.C_NOTE_TEXT if has_note else "#1f2329"))
            tr = QtCore.QRect(bubble.left() + self.PAD_X, bubble.top() + self.PAD_Y,
                              text_avail_w, bubble.height() - self.PAD_Y * 2)
            # 用 clip 防止越界 + 垂直居中单行
            flags = QtCore.Qt.TextFlag.TextWordWrap
            painter.drawText(tr, flags, text)

        # 时间（紧贴气泡底部下方，不压邻行 → 移入移出不再闪烁）
        painter.setPen(QtGui.QColor("#9aa0a8"))
        ft = QtGui.QFont()
        ft.setPointSize(8)
        painter.setFont(ft)
        tw = 120
        t_rect = QtCore.QRect(bubble.left() if not is_self else bubble.right() - tw,
                              t_y, tw, self.TIME_H)
        painter.drawText(t_rect, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.TextFlag.TextSingleLine,
                         m.get("time", "")[-8:])
        painter.restore()

    def sizeHint(self, option, index):
        m = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not m:
            return QtCore.QSize(0, 40)
        text = m.get("text") or ""
        has_note = bool(m.get("has_note"))
        w = option.widget.width() if option.widget else 800
        max_w = min(self.MAX_W, w - 30)
        wrap_w = max_w - self.PAD_X * 2 - (self.BADGE_W if has_note else 0)
        n_lines, need_h = self._layout(text, max(wrap_w, self.PAD_X * 2))
        # TOP_PAD(气泡顶部) + 气泡 + 时间带 + 行间距（与 paint 一致）
        base = max(40, self.TOP_PAD + need_h + self.PAD_Y * 2
                   + self.TIME_H + self.TIME_GAP) + self.GAP
        # 图片消息：按图片显示高度算行高（与 paint 一致）
        media = m.get("media") or {}
        if m.get("type") == 3 and media.get("md5"):
            model = index.model()
            pm = model.pixmap_for(m.get("mid") or "", media["md5"]) if model else None
            if pm is not None:
                ih, _ = self._img_display(pm, self.IMG_MAX_W)
                base = max(base, self.TOP_PAD + ih + self.PAD_Y * 2
                           + self.TIME_H + self.TIME_GAP + self.GAP)
            else:
                base = max(base, self.TOP_PAD + self.IMG_MAX_H + self.PAD_Y * 2
                           + self.TIME_H + self.TIME_GAP + self.GAP)
        return QtCore.QSize(0, base)
# ---------------------------------------------------------------- AI 对话气泡
class AIChatModel(QtCore.QAbstractListModel):
    """AI 对话消息模型：{who: "me"|"ai"|"sys", text, time}。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self.on_reset = None      # 全量替换/清空后的回调（view 重建）
        self.on_appended = None   # add() 之后的回调（view 追加一条气泡）
        self.on_changed = None    # 单条内容变化后的回调（流式刷新）
    def set_items(self, items: list[dict]):
        self.beginResetModel()
        self._items = items
        self.endResetModel()
        if self.on_reset:
            self.on_reset()
    def add(self, item: dict):
        self.beginInsertRows(QtCore.QModelIndex(), len(self._items), len(self._items))
        self._items.append(item)
        self.endInsertRows()
        if self.on_appended:
            self.on_appended(item)
    def clear(self):
        self.beginResetModel()
        self._items = []
        self.endResetModel()
        if self.on_reset:
            self.on_reset()
    def touch_last(self):
        """通知 view：最后一条内容变了（流式刷新，不改数据）。"""
        n = len(self._items) - 1
        if n < 0:
            return
        idx = self.index(n, 0)
        self.dataChanged.emit(idx, idx, [QtCore.Qt.ItemDataRole.UserRole])
        if self.on_changed:
            self.on_changed(self._items[n])
    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._items)
    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        if role == QtCore.Qt.ItemDataRole.UserRole:
            return self._items[index.row()]
        return None


class AIChatView(QtWidgets.QScrollArea):
    """AI 对话区：QScrollArea 容器 + 每条消息一个气泡卡片。

    - AI 消息用 QTextBrowser.setMarkdown() 渲染（粗体/列表/表格/引用/代码块都能显示，
      document 自算完整高度，彻底避免自绘 delegate 最后一行被裁的问题）；
    - 我发的消息用蓝色卡片；系统提示用居中灰字；
    - 支持流式打字机（原地刷新最后一条 AI 气泡）与「AI 思考中」跳动圆点动画。
    数据仍存在 AIChatModel，view 按 model 数据渲染。
    """
    C_BG = "#f2f3f5"
    C_AI_CARD = "#ffffff"
    C_AI_BORDER = "#e1e4e8"
    C_ME_CARD = "#e8f3ff"
    C_ME_BORDER = "#c7dcff"
    C_TEXT = "#1f2329"
    C_SYS = "#8a9099"
    C_ME_AV = "#2f7ae5"
    C_AI_AV = "#12b886"
    MAX_CARD_W = 560          # 卡片最大宽度（超出则不再拉长，像豆包/ChatGPT）
    MIN_CARD_W = 220

    # AI 回答的 Markdown 排版样式（标题/列表/表格/引用/代码/分割线）
    MD_CSS = """
    body { color:#1f2329; line-height:165%; }
    h1 { font-size:17px; font-weight:700; color:#111827; margin:14px 0 8px 0; }
    h2 { font-size:15.5px; font-weight:700; color:#111827; margin:13px 0 7px 0;
         padding-bottom:4px; border-bottom:1px solid #eef1ef; }
    h3 { font-size:14.5px; font-weight:700; color:#12b886; margin:11px 0 6px 0; }
    h4 { font-size:13.5px; font-weight:700; color:#2f7ae5; margin:9px 0 5px 0; }
    p  { margin:6px 0; }
    ul, ol { margin:6px 0 6px 4px; padding-left:20px; }
    li { margin:4px 0; }
    li::marker { color:#12b886; font-weight:700; }
    strong { color:#0b7a5a; font-weight:700; }
    em { color:#3a4640; }
    a { color:#2f7ae5; text-decoration:none; }
    blockquote { background:#f4faf7; border-left:3px solid #12b886; margin:8px 0;
                 padding:7px 12px; color:#3a4640; border-radius:5px; }
    code { background:#eef1ef; color:#c2410c; padding:1px 5px; border-radius:4px;
           font-family:Consolas,monospace; font-size:12.5px; }
    pre { background:#f7f9f8; border:1px solid #e1e4e8; border-radius:8px;
          padding:10px 12px; margin:8px 0; }
    pre code { background:transparent; color:#1f2329; padding:0; }
    table { border-collapse:collapse; margin:9px 0; }
    th { background:#f4faf7; color:#0b7a5a; font-weight:700; }
    th, td { border:1px solid #e1e4e8; padding:5px 10px; font-size:12.5px; }
    tr:nth-child(even) td { background:#fafcfb; }
    hr { border:0; border-top:1px solid #e6ebe8; margin:12px 0; }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setObjectName("ai_chat_list")
        self.setStyleSheet(
            f"QScrollArea#ai_chat_list{{background:{self.C_BG};border:1px solid {C_BORDER};"
            f"border-radius:10px;outline:0;}}")
        self._container = QtWidgets.QWidget()
        self._container.setStyleSheet("background:transparent;")
        self._v = QtWidgets.QVBoxLayout(self._container)
        self._v.setContentsMargins(14, 12, 14, 12)
        self._v.setSpacing(12)
        self._v.addStretch(1)
        self.setWidget(self._container)
        self._model = None
        self._bubbles: list[dict] = []   # [{who, ref(widget), body, browser}]
        self._fit_lock = False

    def set_model(self, model):
        self._model = model

    # ---------- 数据 -> UI ----------

    def clear_bubbles(self):
        while self._v.count() > 1:     # 保留末尾 stretch
            item = self._v.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._bubbles = []

    def rebuild(self):
        """按 model 全量重建气泡（切会话 / 加载历史时用）。"""
        self.clear_bubbles()
        if self._model is None:
            return
        for i in range(self._model.rowCount()):
            it = self._model.data(self._model.index(i, 0),
                                  QtCore.Qt.ItemDataRole.UserRole) or {}
            self._make_bubble(it)
        self._relayout_widths()
        QtCore.QTimer.singleShot(0, self.scrollToBottom)

    def append_item(self, it: dict):
        self._make_bubble(it)
        self._relayout_widths()
        QtCore.QTimer.singleShot(0, self.scrollToBottom)

    def update_last_ai(self, it: dict):
        """流式：原地刷新最后一条 AI 气泡的内容（保留滚动位置）。"""
        for b in reversed(self._bubbles):
            if b["who"] == "ai":
                self._fill_ai(b, it.get("text") or "", bool(it.get("streaming")),
                              bool(it.get("thinking")))
                self._fits(b)
                return

    def set_thinking_dots(self, n: int):
        """把最后一条 thinking AI 气泡的圆点改成 n 个（0/1/2 动画）。"""
        for b in reversed(self._bubbles):
            if b["who"] == "ai" and b.get("browser") is not None:
                b["browser"].setMarkdown("**AI 正在思考**" + (" " + "●" * (n + 1) if n >= 0 else ""))
                self._fits(b)
                return

    # ---------- 气泡构建 ----------

    def _make_bubble(self, it: dict):
        who = it.get("who", "ai")
        text = it.get("text") or ""
        streaming = bool(it.get("streaming"))
        thinking = bool(it.get("thinking"))

        if who == "sys":
            lab = QtWidgets.QLabel(text)
            lab.setWordWrap(True)
            lab.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter)
            lab.setStyleSheet(
                f"color:{self.C_SYS};font-size:12px;background:transparent;"
                f"padding:2px 8px;")
            self._v.insertWidget(self._v.count() - 1, lab)
            self._bubbles.append({"who": "sys", "ref": lab, "body": lab, "browser": None})
            return

        wrap = QtWidgets.QWidget()
        wrap.setStyleSheet("background:transparent;")
        h = QtWidgets.QHBoxLayout(wrap)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(9)

        is_me = (who == "me")
        av = QtWidgets.QLabel("我" if is_me else "AI")
        av.setFixedSize(30, 30)
        av.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        av.setStyleSheet(
            f"border-radius:15px;background:{self.C_ME_AV if is_me else self.C_AI_AV};"
            f"color:#ffffff;font-weight:700;font-size:12px;border:0;")
        h.addWidget(av, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        if is_me:
            body = QtWidgets.QLabel(text)
            body.setWordWrap(True)
            body.setStyleSheet(
                f"background:{self.C_ME_CARD};border:1px solid {self.C_ME_BORDER};"
                f"border-radius:12px;padding:10px 14px;color:{self.C_TEXT};"
                f"font-size:13px;")
            body.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            h.addWidget(body, 1, QtCore.Qt.AlignmentFlag.AlignTop)
            self._v.insertWidget(self._v.count() - 1, wrap)
            self._bubbles.append({"who": "me", "ref": wrap, "body": body, "browser": None})
            return

        # AI：QTextBrowser + Markdown
        browser = QtWidgets.QTextBrowser()
        browser.setReadOnly(True)
        browser.setOpenExternalLinks(True)
        browser.setStyleSheet(
            f"QTextBrowser{{background:{self.C_AI_CARD};border:1px solid {self.C_AI_BORDER};"
            f"border-radius:12px;padding:10px 14px;color:{self.C_TEXT};"
            f"font-size:13px;}}")
        browser.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        browser.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        h.addWidget(browser, 1, QtCore.Qt.AlignmentFlag.AlignTop)
        self._v.insertWidget(self._v.count() - 1, wrap)
        self._bubbles.append({"who": "ai", "ref": wrap, "body": browser, "browser": browser})
        self._fill_ai(self._bubbles[-1], text, streaming, thinking)

    def _fill_ai(self, b: dict, text: str, streaming: bool, thinking: bool):
        browser = b["browser"]
        if thinking:
            browser.setMarkdown("**AI 正在思考** ●")
        else:
            md = text or ""
            if streaming and md:
                # 流式过程中给一段占位，防止 markdown 未闭合造成整块渲染错乱
                md = md + "\n"
            browser.setMarkdown(md)
            # 统一字体（避免离屏/某些环境用框框字），并做完整排版美化
            doc = browser.document()
            if doc:
                doc.setDefaultFont(self._font())
                doc.setDefaultStyleSheet(self.MD_CSS)
        self._fits(b)

    def _font(self):
        f = QtGui.QFont("Microsoft YaHei", 13.5)
        f.setStyleStrategy(QtGui.QFont.StyleStrategy.PreferAntialias)
        return f

    def _fits(self, b: dict):
        """按 document 实际高度设置 QTextBrowser 固定高度，底部内容绝不裁。"""
        browser = b.get("browser")
        if browser is None:
            return
        if self._fit_lock:
            return
        self._fit_lock = True
        try:
            doc = browser.document()
            # 用 viewport 实际可视宽度排版（和真实渲染一致），否则换行数会变
            avail = max(self.MIN_CARD_W - 28, browser.viewport().width() - 4)
            doc.setTextWidth(avail)
            # documentLayout().documentSize() 才是排版后的真实高度；
            # doc.size() 会因为 frame/文档边距少算几像素，导致最后一行被裁
            need = int(doc.documentLayout().documentSize().height())
            need = max(need, int(doc.size().height()))
            browser.setFixedHeight(max(34, need + 24))
        finally:
            self._fit_lock = False

    def _relayout_widths(self, force: bool = True):
        """窗口宽度变化时：重设卡片最大宽度 + AI 气泡 document 宽度。"""
        vw = self.viewport().width() if self.viewport() else 560
        card_w = max(self.MIN_CARD_W, min(self.MAX_CARD_W, vw - 14 * 2 - 30 - 9 - 24))
        for b in self._bubbles:
            if b["who"] in ("me", "ai"):
                try:
                    b["body"].setMaximumWidth(card_w)
                except Exception:
                    pass
            if b.get("browser") is not None:
                self._fits(b)
        self._container.updateGeometry()

    def scrollToBottom(self):
        sb = self.verticalScrollBar()
        QtCore.QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout_widths()


class AIChatDelegate(QtWidgets.QStyledItemDelegate):
    """豆包/ChatGPT 风格：左侧头像 + 白色卡片，AI 卡片带浅色边框，我的提问用蓝色卡片区分。
    流式输出时在卡片底部显示闪烁光标（由模型里的 streaming 字段控制）。"""
    PAD_X, PAD_Y = 15, 12
    LINE_H = 23
    FONT_SZ = 13.5
    GAP = 14                # 卡片之间的间距
    MARGIN_L = 12
    MARGIN_R = 12
    AVATAR = 30
    GAP_AVA = 10            # 头像与卡片间距
    CARD_RATIO = 0.92       # 卡片最大宽度占可用宽度比例
    TOP_PAD = 8
    CARD_R = 12

    C_BG = "#f2f3f5"
    C_AI_CARD = "#ffffff"
    C_AI_BORDER = "#e1e4e8"
    C_ME_CARD = "#e8f3ff"
    C_ME_BORDER = "#c7dcff"
    C_TEXT = "#1f2329"
    C_SYS = "#8a9099"
    C_ME_AV = "#2f7ae5"
    C_AI_AV = "#12b886"
    C_CURSOR = "#12b886"

    def _font(self):
        f = QtGui.QFont()
        f.setPointSize(self.FONT_SZ)
        return f

    def _card_max_w(self, option):
        w = option.widget.width() if option.widget else 420
        avail = w - self.MARGIN_L - self.MARGIN_R - self.AVATAR - self.GAP_AVA
        return max(160, int(avail * self.CARD_RATIO))

    def _layout(self, text, avail_w):
        fm = QtGui.QFontMetrics(self._font())
        total = 0
        for ln in (text or "").split("\n"):
            if not ln:
                total += 1
                continue
            r = fm.boundingRect(0, 0, avail_w, 10000,
                                QtCore.Qt.TextFlag.TextWordWrap, ln)
            h = r.height()
            total += max(1, h // self.LINE_H + (1 if h % self.LINE_H else 0))
        return total, total * self.LINE_H

    def _card_w(self, fm, text, avail_w):
        worst = 0
        for ln in (text or "").split("\n"):
            if ln:
                worst = max(worst, fm.horizontalAdvance(ln))
        return min(avail_w, worst + self.PAD_X * 2 + 2)

    def paint(self, painter, option, index):
        it = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not it:
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r = option.rect
        painter.fillRect(r, QtGui.QColor(self.C_BG))
        who = it.get("who", "ai")
        text = it.get("text") or ""
        f = self._font()
        painter.setFont(f)
        fm = painter.fontMetrics()

        # 系统提示：居中浅灰文字（小字）
        if who == "sys":
            painter.setPen(QtGui.QColor(self.C_SYS))
            h = fm.boundingRect(0, 0, r.width() - 28, 10000,
                                QtCore.Qt.TextFlag.TextWordWrap, text).height()
            painter.drawText(QtCore.QRect(r.left() + 14, r.top() + self.TOP_PAD,
                                          r.width() - 28, max(16, h)),
                             int(QtCore.Qt.AlignmentFlag.AlignHCenter
                                 | QtCore.Qt.TextFlag.TextWordWrap), text)
            painter.restore()
            return

        is_me = (who == "me")
        max_w = self._card_max_w(option)
        card_w = self._card_w(fm, text, max_w)
        _n, need_h = self._layout(text, max(card_w - self.PAD_X * 2 - 2, 40))
        streaming = bool(it.get("streaming"))
        cur_h = 14 if streaming else 0
        card_h = max(34, need_h + self.PAD_Y * 2 + cur_h)

        ax = r.left() + self.MARGIN_L
        cy = r.top() + self.TOP_PAD
        card = QtCore.QRect(ax + self.AVATAR + self.GAP_AVA, cy, card_w, card_h)

        # 卡片
        painter.setPen(QtGui.QColor(self.C_ME_BORDER if is_me else self.C_AI_BORDER))
        painter.setBrush(QtGui.QColor(self.C_ME_CARD if is_me else self.C_AI_CARD))
        painter.drawRoundedRect(card, self.CARD_R, self.CARD_R)

        # 头像（左侧圆形）
        ava = QtCore.QRect(ax, cy, self.AVATAR, self.AVATAR)
        painter.setPen(QtGui.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor(self.C_ME_AV if is_me else self.C_AI_AV))
        painter.drawEllipse(ava)
        painter.setPen(QtGui.QColor("#ffffff"))
        f2 = self._font(); f2.setPointSize(10.5); f2.setBold(True)
        painter.setFont(f2)
        painter.drawText(ava, QtCore.Qt.AlignmentFlag.AlignCenter, "我" if is_me else "AI")

        # 正文
        painter.setFont(f)
        painter.setPen(QtGui.QColor(self.C_TEXT))
        body = QtCore.QRect(card.left() + self.PAD_X, card.top() + self.PAD_Y,
                            card_w - self.PAD_X * 2, card_h - self.PAD_Y * 2)
        painter.drawText(body, int(QtCore.Qt.TextFlag.TextWordWrap), text)

        # 流式光标（闪烁竖条）
        if streaming:
            painter.setPen(QtGui.QColor(self.C_CURSOR))
            bx = card.left() + self.PAD_X
            by = card.bottom() - self.PAD_Y - 11
            painter.drawRect(QtCore.QRectF(bx + 2, by, 7, 12))
        painter.restore()

    def sizeHint(self, option, index):
        it = index.data(QtCore.Qt.ItemDataRole.UserRole)
        if not it:
            return QtCore.QSize(0, 40)
        text = it.get("text") or ""
        if it.get("who") == "sys":
            fm = QtGui.QFontMetrics(self._font())
            w = option.widget.width() if option.widget else 420
            h = fm.boundingRect(0, 0, max(60, w - 28), 10000,
                                QtCore.Qt.TextFlag.TextWordWrap, text).height()
            return QtCore.QSize(0, h + self.TOP_PAD + self.GAP)
        max_w = self._card_max_w(option)
        fm = QtGui.QFontMetrics(self._font())
        card_w = self._card_w(fm, text, max_w)
        _n, need_h = self._layout(text, max(card_w - self.PAD_X * 2 - 2, 40))
        cur_h = 14 if it.get("streaming") else 0
        h = self.TOP_PAD + max(34, need_h + self.PAD_Y * 2 + cur_h) + self.GAP
        return QtCore.QSize(0, h)


# ---------------------------------------------------------------- 主窗口
class AISettingsDialog(QtWidgets.QDialog):
    """AI 配置弹窗：分组卡片式，深色圆角，带状态标签。"""
    FIELD_QSS = (
        f"QLineEdit,QSpinBox{{background:{C_BG};border:1px solid {C_BORDER};"
        f"border-radius:8px;padding:8px 12px;color:{C_TEXT};font-size:13px;}}"
        f"QLineEdit:focus,QSpinBox:focus{{border-color:{C_ACCENT};}}"
    )
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.setWindowTitle("💡 AI 聊天教练设置")
        self.setModal(True)
        self.setFixedWidth(480)
        self.setStyleSheet(f"QDialog{{background:{C_BG_2};}}")
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)
        # 标题区
        title = QtWidgets.QLabel("AI 聊天教练")
        title.setStyleSheet(f"color:#fff;font-size:17px;font-weight:700;")
        sub = QtWidgets.QLabel("对方发消息时给 3 个回复方案 + 讲解，帮你越聊越好")
        sub.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12px;")
        root.addWidget(title)
        root.addWidget(sub)
        # 卡片 1：接口配置
        card1 = QtWidgets.QFrame()
        card1.setStyleSheet(
            f"QFrame{{background:{C_BG_3};border-radius:12px;}}")
        c1 = QtWidgets.QVBoxLayout(card1)
        c1.setContentsMargins(16, 14, 16, 14)
        c1.setSpacing(10)
        h_api = QtWidgets.QLabel("🚀 接口")
        h_api.setStyleSheet(f"color:{C_ACCENT_2};font-size:13px;font-weight:600;")
        c1.addWidget(h_api)
        self.ed_api = self._field("API 地址", cfg.get("api_url", ""), c1)
        self.ed_key = self._field("API 密钥", cfg.get("api_key", ""), c1, password=True)
        # 模型：下拉选择预设（可直接切换），也允许手动输入
        model_row = QtWidgets.QHBoxLayout()
        m_lab = QtWidgets.QLabel("模型")
        m_lab.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12.5px;min-width:64px;")
        self.ed_model = QtWidgets.QComboBox()
        self.ed_model.setEditable(True)
        self.ed_model.addItems(PRESET_MODELS)
        cur = cfg.get("model", "") or ""
        if cur and self.ed_model.findText(cur) < 0:
            self.ed_model.addItem(cur)
        self.ed_model.setCurrentText(cur)
        self.ed_model.setStyleSheet(self.FIELD_QSS)
        model_row.addWidget(m_lab)
        model_row.addWidget(self.ed_model, 1)
        c1.addLayout(model_row)
        # 连接测试按钮
        self.btn_test = QtWidgets.QPushButton("一键测试连接")
        self.btn_test.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_ACCENT_2};border:1px solid {C_ACCENT};"
            f"border-radius:6px;padding:5px 12px;font-size:12px;}}"
            f"QPushButton:hover{{background:{C_ACCENT_2};color:#fff;}}")
        self.btn_test.clicked.connect(self._test_conn)
        self.lbl_test = QtWidgets.QLabel("")
        self.lbl_test.setStyleSheet(f"color:{C_TEXT_DIM};font-size:11.5px;")
        self.lbl_test.setWordWrap(True)
        t_row = QtWidgets.QHBoxLayout()
        t_row.addWidget(self.btn_test)
        t_row.addWidget(self.lbl_test, 1)
        c1.addLayout(t_row)
        root.addWidget(card1)
        # 卡片 2：行为
        card2 = QtWidgets.QFrame()
        card2.setStyleSheet(
            f"QFrame{{background:{C_BG_3};border-radius:12px;}}")
        c2 = QtWidgets.QVBoxLayout(card2)
        c2.setContentsMargins(16, 14, 16, 14)
        c2.setSpacing(10)
        h_act = QtWidgets.QLabel("⚙️ 行为")
        h_act.setStyleSheet(f"color:{C_ACCENT_2};font-size:13px;font-weight:600;")
        c2.addWidget(h_act)
        # 人格底色（用户自定义 AI 扮演的自己）
        p_lab = QtWidgets.QLabel("人格底色（AI 扮演你的风格）")
        p_lab.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12.5px;")
        c2.addWidget(p_lab)
        self.ed_persona = QtWidgets.QTextEdit()
        self.ed_persona.setPlainText(cfg.get("persona", ""))
        self.ed_persona.setPlaceholderText("例：幽默毒舌但不油腻 / 温柔靠谱 / 高冷神秘 / 直球大胆…\n首次喂入聊天记录时，AI 会按这个人格底色来分析并出方案。")
        self.ed_persona.setFixedHeight(70)
        self.ed_persona.setStyleSheet(
            f"QTextEdit{{background:{C_BG};border:1px solid {C_BORDER};border-radius:8px;"
            f"padding:8px;color:{C_TEXT};font-size:13px;}}"
            f"QTextEdit:focus{{border-color:{C_ACCENT};}}")
        c2.addWidget(self.ed_persona)
        # 自定义分析指令（用户想重点看什么）
        at_lab = QtWidgets.QLabel("分析指令（可选，AI 分析这段聊天时重点看什么）")
        at_lab.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12.5px;")
        c2.addWidget(at_lab)
        self.ed_analysis_task = QtWidgets.QTextEdit()
        self.ed_analysis_task.setPlainText(cfg.get("analysis_task", ""))
        self.ed_analysis_task.setPlaceholderText(
            "例：她是不是把我当备胎？我哪里说得太舔了？我们推进到什么程度合适？\n"
            "留空使用默认任务书：判断对方兴趣/关系阶段 + 指出我踩的坑 + 给可直接发出的下一句。")
        self.ed_analysis_task.setFixedHeight(64)
        self.ed_analysis_task.setStyleSheet(
            f"QTextEdit{{background:{C_BG};border:1px solid {C_BORDER};border-radius:8px;"
            f"padding:8px;color:{C_TEXT};font-size:13px;}}"
            f"QTextEdit:focus{{border-color:{C_ACCENT};}}")
        c2.addWidget(self.ed_analysis_task)
        # 上下文条数
        ctx_row = QtWidgets.QHBoxLayout()
        ctx_lab = QtWidgets.QLabel("上下文条数")
        ctx_lab.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12.5px;")
        self.ed_ctx = QtWidgets.QSpinBox()
        self.ed_ctx.setRange(20, 400)
        self.ed_ctx.setValue(int(cfg.get("max_context_msgs", 80)))
        self.ed_ctx.setStyleSheet(self.FIELD_QSS)
        ctx_row.addWidget(ctx_lab)
        ctx_row.addStretch()
        ctx_row.addWidget(self.ed_ctx)
        c2.addLayout(ctx_row)
        self.cb_enable = QtWidgets.QCheckBox("启用 AI 建议（对方新消息自动提示下一句）")
        self.cb_enable.setChecked(bool(cfg.get("enabled")))
        self.cb_enable.setStyleSheet(f"color:{C_TEXT};font-size:13px;spacing:8px;")
        c2.addWidget(self.cb_enable)
        self.cb_autocopy = QtWidgets.QCheckBox("自动复制建议到剪贴板")
        self.cb_autocopy.setChecked(bool(cfg.get("auto_copy")))
        self.cb_autocopy.setStyleSheet(f"color:{C_TEXT};font-size:13px;spacing:8px;")
        c2.addWidget(self.cb_autocopy)
        root.addWidget(card2)
        # 提示
        tip = QtWidgets.QLabel("已内置 inferaiapi.com 网关（mimo 系列 / deepseek-v4 系列）。模型慢可换成 deepseek-v4-flash 或 deepseek-v4.1-flash；也支持任何 OpenAI 兼容接口。")
        tip.setStyleSheet(f"color:{C_TEXT_DIM};font-size:11.5px;")
        tip.setWordWrap(True)
        root.addWidget(tip)
        # 按钮
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch()
        b_cancel = QtWidgets.QPushButton("取消")
        b_cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT_DIM};border:1px solid {C_BORDER};"
            f"border-radius:8px;padding:8px 22px;font-size:13px;}}"
            f"QPushButton:hover{{border-color:{C_TEXT_DIM};}}")
        b_cancel.clicked.connect(self.reject)
        b_ok = QtWidgets.QPushButton("保存")
        b_ok.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {C_ACCENT_2},stop:1 {C_ACCENT});color:#fff;"
            f"border-radius:8px;padding:8px 30px;font-size:13px;font-weight:600;}}"
            f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 #4be893,stop:1 {C_ACCENT});}}")
        b_ok.clicked.connect(self._ok)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        root.addLayout(btns)
    def _field(self, label: str, value: str, parent_lay, password: bool = False) -> QtWidgets.QLineEdit:
        row = QtWidgets.QHBoxLayout()
        lab = QtWidgets.QLabel(label)
        lab.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12.5px;min-width:64px;")
        ed = QtWidgets.QLineEdit(value)
        if password:
            ed.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        ed.setStyleSheet(self.FIELD_QSS)
        row.addWidget(lab)
        row.addWidget(ed, 1)
        parent_lay.addLayout(row)
        return ed
    def _ok(self):
        self.cfg["api_url"] = self.ed_api.text().strip()
        self.cfg["api_key"] = self.ed_key.text().strip()
        self.cfg["model"] = self.ed_model.currentText().strip() or "mimo-v2.6-pro"
        self.cfg["max_context_msgs"] = int(self.ed_ctx.value())
        self.cfg["persona"] = self.ed_persona.toPlainText().strip()
        self.cfg["analysis_task"] = self.ed_analysis_task.toPlainText().strip()
        self.cfg["enabled"] = self.cb_enable.isChecked()
        self.cfg["auto_copy"] = self.cb_autocopy.isChecked()
        self.accept()
    def _test_conn(self):
        """一键测试：用当前填写的接口/密钥/模型发一条最小请求。"""
        self.lbl_test.setText("⏳ 测试中…（推理模型可能要等十几秒）")
        self.btn_test.setEnabled(False)
        cfg = {
            "api_url": self.ed_api.text().strip(),
            "api_key": self.ed_key.text().strip(),
            "model": self.ed_model.currentText().strip(),
        }
        import threading as _t
        def task():
            r = test_connection(cfg, timeout=70)
            QtCore.QMetaObject.invokeMethod(
                self, "_test_done", QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(str, r["ok"]), QtCore.Q_ARG(str, r["msg"]),
                QtCore.Q_ARG(str, r.get("content", "")))
        _t.Thread(target=task, daemon=True).start()
    @QtCore.Slot(str, str, str)
    def _test_done(self, ok: str, msg: str, content: str):
        self.btn_test.setEnabled(True)
        self.lbl_test.setText(msg)
class MainWindow(QtWidgets.QMainWindow):
    MAX_BUBBLES = 800
    _init_done = QtCore.Signal(str, str)
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1680, 940)
        self.setMinimumSize(1180, 680)
        self.setStyleSheet(QSS)
        self.store = None
        self._media_store = None   # 常驻 MediaStore（解析 cache 明文图）
        self.account = None
        self.watcher = None
        self._worker = None
        self._contacts_loading = False
        self._contact_display = []
        self._alias_map: dict[str, str] = {}
        self._pending_counts: dict | None = None
        self.ai = AIClient(DATA_DIR)
        self.ai_gen = None
        self._ai_first_pending = False
        self._rv_gen = None  # AI 复盘生成线程
        self._ai_loading_session = False  # 会话下拉框/模型正在程序化更新（防信号回环）
        self._ai_session_talkers: list[str] = []
        self._msgs_cache: dict[str, list] = {}  # talker -> 消息列表缓存（切换秒开）
        self._msg_refresh_seq = 0
        self._media_key_worker = None
        self._cur_talker = None
        self._cur_msgs = []
        self._cur_peer = ""
        self._build_ui()
        self._init_done.connect(self._load_account)
        self._status("启动中…")
        self._start_init()
    # ------------------------------------------------------------ UI
    def _build_ui(self):
        central = QtWidgets.QWidget(self)
        central.setObjectName("root")
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # ---- 顶部
        top = QtWidgets.QWidget()
        top.setObjectName("topbar")
        top.setFixedHeight(58)
        top_lay = QtWidgets.QHBoxLayout(top)
        top_lay.setContentsMargins(16, 0, 16, 0)
        title = QtWidgets.QLabel("🟢 微聊助手")
        title.setObjectName("app_title")
        self.lbl_acc = QtWidgets.QLabel("未连接")
        self.lbl_acc.setObjectName("acc_label")
        self.lbl_status = QtWidgets.QLabel("")
        self.lbl_status.setObjectName("status_label")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setObjectName("bar")
        self.progress.setFixedWidth(200)
        self.progress.setVisible(False)
        self.btn_extract = QtWidgets.QPushButton("提取密钥并解密")
        self.btn_extract.setObjectName("btn_extract")
        self.btn_extract.clicked.connect(self._on_extract)
        self.btn_ai_settings = QtWidgets.QPushButton("⚙ AI")
        self.btn_ai_settings.setStyleSheet(
            f"QPushButton{{background:rgba(255,255,255,.12);color:#ffffff;border:1px solid rgba(255,255,255,.38);"
            f"border-radius:7px;padding:6px 13px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,.22);border-color:#ffffff;}}")
        self.btn_ai_settings.clicked.connect(self._open_ai_settings)
        self.btn_mediakey = QtWidgets.QPushButton("🎨 媒体密钥")
        self.btn_mediakey.setStyleSheet(
            f"QPushButton{{background:rgba(255,255,255,.12);color:#d8e8ff;border:1px solid rgba(255,255,255,.38);"
            f"border-radius:7px;padding:6px 13px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,.22);border-color:#ffffff;}}")
        self.btn_mediakey.clicked.connect(self._extract_media_key)
        self.btn_switch_acc = QtWidgets.QPushButton("👤 切换账号")
        self.btn_switch_acc.setStyleSheet(
            f"QPushButton{{background:rgba(255,255,255,.12);color:#ffe8b8;border:1px solid rgba(255,255,255,.38);"
            f"border-radius:7px;padding:6px 13px;}}"
            f"QPushButton:hover{{background:rgba(255,255,255,.22);border-color:#ffffff;}}")
        self.btn_switch_acc.setToolTip("本机登录过多个微信时，选择要解密/查看哪个账号")
        self.btn_switch_acc.clicked.connect(self._switch_account)
        top_lay.addWidget(title)
        top_lay.addSpacing(14)
        top_lay.addWidget(self.lbl_acc)
        top_lay.addStretch()
        top_lay.addWidget(self.lbl_status)
        top_lay.addSpacing(10)
        top_lay.addWidget(self.progress)
        top_lay.addSpacing(6)
        top_lay.addWidget(self.btn_extract)
        top_lay.addWidget(self.btn_mediakey)
        top_lay.addWidget(self.btn_switch_acc)
        top_lay.addWidget(self.btn_ai_settings)
        root.addWidget(top)
        # ---- 分栏
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        # 左侧联系人
        left_panel = QtWidgets.QWidget()
        left_panel.setObjectName("side")
        left_panel.setStyleSheet(f"QWidget#side{{background:{C_BG_2};}}")
        lp = QtWidgets.QVBoxLayout(left_panel)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.setSpacing(0)
        head = QtWidgets.QLabel("  联系人")
        head.setStyleSheet(
            f"color:{C_TEXT};font-size:13px;font-weight:600;padding:12px 14px;"
            f"background:{C_BG_3};border-bottom:1px solid {C_BORDER};")
        # 联系人搜索框
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("🔍 搜索联系人：昵称 / 备注 / 微信号 / wxid")
        self.search_edit.setStyleSheet(
            f"QLineEdit{{background:#ffffff;border:1px solid {C_BORDER};border-radius:9px;"
            f"padding:7px 12px;color:{C_TEXT};font-size:13px;}}"
            f"QLineEdit:focus{{border-color:{C_ACCENT};background:#fbfffd;}}")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_contacts)
        self.contact_list = QtWidgets.QListView()
        self.contact_list.setObjectName("contact_list")
        self.contact_model = ContactModel(self)
        self.contact_list.setModel(self.contact_model)
        self.contact_list.setItemDelegate(ContactDelegate(self.contact_list))
        self.contact_list.setFixedWidth(330)
        self.contact_list.setMouseTracking(True)
        self.contact_list.clicked.connect(self._on_contact_clicked)
        lp.addWidget(head)
        lp.addWidget(self.search_edit)
        lp.addWidget(self.contact_list, 1)
        split.addWidget(left_panel)
        # 右侧聊天
        right = QtWidgets.QWidget()
        right.setObjectName("chatroot")
        rp = QtWidgets.QVBoxLayout(right)
        rp.setContentsMargins(0, 0, 0, 0)
        rp.setSpacing(0)
        self.chat_head = QtWidgets.QLabel("  选择左侧联系人，查看聊天记录")
        self.chat_head.setStyleSheet(
            f"color:{C_TEXT};padding:11px 16px;background:{C_BG_3};font-size:13.5px;font-weight:600;"
            f"border-bottom:1px solid {C_BORDER};")
        self.chat_view = ChatListView()
        self.chat_view.setObjectName("chat_scroll")
        self.chat_view.setStyleSheet(f"QListView{{background:{C_BG};border:0;outline:0;}}")
        self.chat_model = MessageModel(self)
        self.chat_view.setModel(self.chat_model)
        self.chat_view.setItemDelegate(MessageDelegate(self.chat_view))
        self.chat_view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        # 行高不统一（气泡高度随文本行数变化），关闭 uniformItemSizes，
        # 否则 Qt 会按统一高度估算/局部重绘，鼠标移入移出时邻行内容会错位闪烁
        self.chat_view.setUniformItemSizes(False)
        self.chat_view.setMouseTracking(True)
        # 多选支持（Ctrl/Shift 选多条 → 批量写/删笔记）
        self.chat_view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.chat_view.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_view.customContextMenuRequested.connect(self._chat_menu)
        rp.addWidget(self.chat_head)
        rp.addWidget(self.chat_view, 1)
        split.addWidget(right)
        # ---- 右侧 AI 面板（独立第三栏，AI 分析/方案/复盘都在这）
        right_ai = QtWidgets.QWidget()
        right_ai.setObjectName("ai_side")
        right_ai.setStyleSheet(f"QWidget#ai_side{{background:{C_BG_2};}}")
        ral = QtWidgets.QVBoxLayout(right_ai)
        ral.setContentsMargins(0, 0, 0, 0)
        ral.setSpacing(0)
        # AI 对话窗口（占满右栏）：和 AI 自由对话，用来分析聊天记录
        ai_panel = QtWidgets.QWidget()
        ai_panel.setObjectName("ai_panel")
        ai_panel.setStyleSheet(
            f"QWidget#ai_panel{{background:{C_BG_2};border-bottom:1px solid {C_BORDER};}}")
        ai_lay = QtWidgets.QVBoxLayout(ai_panel)
        ai_lay.setContentsMargins(14, 12, 14, 10)
        ai_lay.setSpacing(8)
        ai_label = QtWidgets.QLabel("💬 与 AI 对话 · 分析这段聊天")
        ai_label.setStyleSheet(f"color:{C_ACCENT};font-size:14px;font-weight:700;")
        ai_lay.addWidget(ai_label)
        # ---- 会话条：像 ChatBox 一样支持多个 AI 会话（每个联系人一个独立会话），
        #      可切换 / 重命名 / 清空 / 删除，历史持久化到 data/ai_chats.json
        self.ai_session_bar = QtWidgets.QWidget()
        self.ai_session_bar.setObjectName("ai_session_bar")
        self.ai_session_bar.setStyleSheet(
            f"QWidget#ai_session_bar{{background:{C_BG_3};border:1px solid {C_BORDER};"
            f"border-radius:9px;}}")
        asb = QtWidgets.QHBoxLayout(self.ai_session_bar)
        asb.setContentsMargins(8, 5, 6, 5)
        asb.setSpacing(6)
        asb_icon = QtWidgets.QLabel("💭")
        asb_icon.setStyleSheet("font-size:12px;")
        asb.addWidget(asb_icon)
        self.cmb_ai_session = QtWidgets.QComboBox()
        self.cmb_ai_session.setMinimumWidth(150)
        self.cmb_ai_session.setToolTip("切换 AI 会话：每个联系人一个独立会话，互不干扰")
        self.cmb_ai_session.setStyleSheet(
            f"QComboBox{{background:#ffffff;border:1px solid {C_BORDER};border-radius:7px;"
            f"padding:4px 8px;color:{C_TEXT};font-size:12px;}}"
            f"QComboBox:focus{{border-color:{C_ACCENT};}}")
        self.cmb_ai_session.currentIndexChanged.connect(self._on_ai_session_switch)
        asb.addWidget(self.cmb_ai_session, 1)
        self.btn_ai_sess_rename = QtWidgets.QPushButton("✏️")
        self.btn_ai_sess_clear = QtWidgets.QPushButton("🧹")
        self.btn_ai_sess_del = QtWidgets.QPushButton("🗑")
        for b, tip in ((self.btn_ai_sess_rename, "重命名当前会话"),
                       (self.btn_ai_sess_clear, "清空当前会话的消息（保留补充场景）"),
                       (self.btn_ai_sess_del, "删除当前会话（消息 + 补充场景 + AI 上下文）")):
            b.setToolTip(tip)
            b.setFixedWidth(30)
            b.setStyleSheet(
                f"QPushButton{{background:#ffffff;border:1px solid {C_BORDER};border-radius:7px;"
                f"padding:3px 0;font-size:12px;color:{C_TEXT_DIM};}}"
                f"QPushButton:hover{{border-color:{C_ACCENT};color:{C_ACCENT};}}"
                f"QPushButton:disabled{{color:#c3cbc7;background:#f6f8f7;}}")
            asb.addWidget(b, 0)
        self.btn_ai_sess_rename.clicked.connect(self._ai_sess_rename)
        self.btn_ai_sess_clear.clicked.connect(self._ai_sess_clear)
        self.btn_ai_sess_del.clicked.connect(self._ai_sess_delete)
        ai_lay.addWidget(self.ai_session_bar)
        # 对话历史区：网页式气泡（AI 消息 Markdown 渲染，QTextBrowser 自算高度不截断）
        self.ai_text = AIChatView()
        self.ai_chat_model = AIChatModel(self)
        self.ai_text.set_model(self.ai_chat_model)
        self.ai_chat_model.on_reset = self.ai_text.rebuild
        self.ai_chat_model.on_appended = self.ai_text.append_item
        self.ai_chat_model.on_changed = self.ai_text.update_last_ai
        ai_lay.addWidget(self.ai_text, 1)
        # 手动触发：点击后 AI 才分析这段聊天（不会自动分析）
        btn_ai_analyze_row = QtWidgets.QHBoxLayout()
        self.btn_ai_analyze = QtWidgets.QPushButton("🤖 让 AI 分析这段聊天")
        self.btn_ai_analyze.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:#fff;border:0;border-radius:8px;"
            f"padding:8px 14px;font-size:13px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_ACCENT_2};}}"
            f"QPushButton:disabled{{background:#9fc5b8;color:#fff;}}")
        self.btn_ai_analyze.setEnabled(False)
        self.btn_ai_analyze.setToolTip("把这段聊天的全量记录（谁说的、几点发的）交给恋爱教练 AI 分析")
        self.btn_ai_analyze.clicked.connect(self._manual_ai)
        btn_ai_analyze_row.addWidget(self.btn_ai_analyze, 1)
        ai_lay.addLayout(btn_ai_analyze_row)
        # 补充场景：不在聊天记录里的背景/线下场景/已知信息，提问和复盘时一并给 AI
        extra_row = QtWidgets.QHBoxLayout()
        self.ai_extra = QtWidgets.QTextEdit()
        self.ai_extra.setPlaceholderText(
            "＋ 补充场景（可选）：聊天记录里没有、但 AI 分析必须知道的信息\n"
            "例如：认识三个月 / 她刚换工作很焦虑 / 见过两次面她叫过我哥 / 我生日她记得 / "
            "她说她前男友很渣\n"
            "（会被当作重点依据，和全量聊天记录一起发给恋爱教练）")
        self.ai_extra.setFixedHeight(58)
        self.ai_extra.setStyleSheet(
            f"QTextEdit{{background:#fffbf2;border:1px dashed {C_BORDER};border-radius:8px;"
            f"color:{C_TEXT};font-size:12px;padding:6px;}}")
        self.ai_extra.setToolTip("这些内容不在微信聊天记录里，但会一起发给 AI 参与分析")
        extra_row.addWidget(self.ai_extra, 1)
        self.btn_ai_extra_toggle = QtWidgets.QPushButton("📎")
        self.btn_ai_extra_toggle.setCheckable(True)
        self.btn_ai_extra_toggle.setToolTip("展开/收起「补充场景」输入框")
        self.btn_ai_extra_toggle.setStyleSheet(
            f"QPushButton{{background:{C_BG};color:{C_TEXT_DIM};border:1px solid {C_BORDER};"
            f"border-radius:8px;padding:6px 10px;font-size:13px;}}"
            f"QPushButton:checked{{background:{C_ACCENT};color:#fff;}}")
        extra_row.addWidget(self.btn_ai_extra_toggle, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        ai_lay.addLayout(extra_row)
        # 补充场景默认收起（点 📎 展开），把空间留给聊天框
        self.btn_ai_extra_toggle.setChecked(False)
        self.ai_extra.setVisible(False)
        self.btn_ai_extra_toggle.toggled.connect(self.ai_extra.setVisible)
        # 对话输入区（多行，Ctrl+Enter 发送；Enter 换行）
        self.ai_input = QtWidgets.QTextEdit()
        self.ai_input.setPlaceholderText("问 AI 任何问题…（Ctrl+Enter 发送，Enter 换行）")
        self.ai_input.setFixedHeight(96)
        self.ai_input.setStyleSheet(
            f"QTextEdit{{background:#ffffff;border:1px solid {C_BORDER};border-radius:10px;"
            f"padding:8px 12px;color:{C_TEXT};font-size:13px;}}"
            f"QTextEdit:focus{{border-color:{C_ACCENT};}}")
        self.ai_input.installEventFilter(self)
        self.btn_ai_send = QtWidgets.QPushButton("发送")
        self.btn_ai_send.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:#fff;border:0;border-radius:8px;"
            f"padding:10px 18px;font-size:13px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_ACCENT_2};}}")
        self.btn_ai_send.setEnabled(False)
        self.btn_ai_send.clicked.connect(self._send_ai_msg)
        input_wrap = QtWidgets.QHBoxLayout()
        input_wrap.addWidget(self.ai_input, 1)
        input_wrap.addWidget(self.btn_ai_send, 0, QtCore.Qt.AlignmentFlag.AlignBottom)
        ai_lay.addLayout(input_wrap)
        self.ai_status = QtWidgets.QLabel("")
        self.ai_status.setStyleSheet(f"color:{C_TEXT_DIM};font-size:11.5px;")
        self.ai_status.setWordWrap(True)
        ai_lay.addWidget(self.ai_status)
        self.ai_panel = ai_panel
        # AI 对话占右栏绝大部分（复盘面板折叠后几乎占满）
        ral.addWidget(ai_panel, 1000)

        # ---- 复盘面板：默认折叠（只留一条标题栏），点标题展开
        rv_collapse = QtWidgets.QWidget()
        rv_collapse.setObjectName("review_collapse")
        rv_collapse.setStyleSheet(
            f"QWidget#review_collapse{{background:{C_BG_3};border-top:1px solid {C_BORDER};}}")
        rvc_lay = QtWidgets.QVBoxLayout(rv_collapse)
        rvc_lay.setContentsMargins(14, 4, 14, 4)
        rvc_lay.setSpacing(0)
        rvc_head = QtWidgets.QHBoxLayout()
        self.btn_rv_toggle = QtWidgets.QPushButton("▸  📝 聊天复盘 · 笔记 · 教练报告")
        self.btn_rv_toggle.setCheckable(True)
        self.btn_rv_toggle.setChecked(False)          # 默认折叠
        self.btn_rv_toggle.setStyleSheet(
            f"QPushButton{{background:transparent;border:0;color:{C_ACCENT};"
            f"font-size:12.5px;font-weight:600;text-align:left;padding:4px 0;}}"
            f"QPushButton:hover{{color:{C_ACCENT_2};}}")
        self.btn_rv_toggle.setToolTip("点此展开 / 折叠复盘面板（笔记、星标、教练报告）")
        self.btn_rv_toggle.clicked.connect(self._toggle_review_panel)
        rvc_head.addWidget(self.btn_rv_toggle, 1)
        self.btn_rv_ai = QtWidgets.QPushButton("✨ 一键教练报告")
        self.btn_rv_ai.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:#fff;border:0;border-radius:6px;"
            f"padding:4px 12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_ACCENT_2};}}")
        self.btn_rv_ai.setEnabled(False)
        self.btn_rv_ai.clicked.connect(self._manual_review)
        rvc_head.addWidget(self.btn_rv_ai, 0)
        self.btn_rv_export = QtWidgets.QPushButton("📤 导出复盘")
        self.btn_rv_export.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:#fff;border:0;border-radius:6px;"
            f"padding:4px 12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_ACCENT_2};}}")
        self.btn_rv_export.setEnabled(False)
        self.btn_rv_export.clicked.connect(self._export_review)
        rvc_head.addWidget(self.btn_rv_export, 0)
        ral.addWidget(rv_collapse, 0)

        # 复盘面板本体（折叠时隐藏）
        rv = QtWidgets.QWidget()
        rv.setObjectName("review_panel")
        rv.setStyleSheet(f"QWidget#review_panel{{background:{C_BG_2};border-top:1px solid {C_BORDER};}}")
        rv_lay = QtWidgets.QVBoxLayout(rv)
        rv_lay.setContentsMargins(16, 8, 16, 8)
        rv_lay.setSpacing(6)
        # 搜索笔记（跨聊天）
        srch_row = QtWidgets.QHBoxLayout()
        srch_lab = QtWidgets.QLabel("🔍 搜笔记：")
        srch_lab.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12px;")
        self.srch_edit = QtWidgets.QLineEdit()
        self.srch_edit.setPlaceholderText("跨聊天搜索你的笔记 / 星标…（回车）")
        self.srch_edit.setStyleSheet(
            f"QLineEdit{{background:{C_BG};border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:4px 10px;color:{C_TEXT};}}")
        self.srch_edit.returnPressed.connect(self._search_notes)
        srch_row.addWidget(srch_lab)
        srch_row.addWidget(self.srch_edit, 1)
        rv_lay.addLayout(srch_row)
        # 聊天笔记编辑（失焦保存）
        note_row = QtWidgets.QHBoxLayout()
        note_lab = QtWidgets.QLabel("聊天笔记：")
        note_lab.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12px;")
        self.rv_note = QtWidgets.QLineEdit()
        self.rv_note.setPlaceholderText("给这段聊天写笔记 / 评价 / 待办…（回车保存）")
        self.rv_note.setStyleSheet(
            f"QLineEdit{{background:{C_BG};border:1px solid {C_BORDER};border-radius:6px;"
            f"padding:5px 10px;color:{C_TEXT};}}")
        self.rv_note.returnPressed.connect(self._save_chat_note)
        note_row.addWidget(note_lab)
        note_row.addWidget(self.rv_note, 1)
        rv_lay.addLayout(note_row)
        # AI 复盘 / 重要消息区（多行文本，可滚动）
        self.rv_text = QtWidgets.QTextEdit()
        self.rv_text.setReadOnly(True)
        self.rv_text.setStyleSheet(
            f"QTextEdit{{background:#ffffff;border:1px solid {C_BORDER};border-radius:8px;"
            f"color:{C_TEXT};font-size:12px;padding:8px;}}")
        rv_lay.addWidget(self.rv_text, 1)
        self.review_panel = rv
        self.review_collapse_bar = rv_collapse
        ral.addWidget(rv, 0)        # 复盘本体：展开时才占空间
        rv.setVisible(False)        # 默认折叠

        split.addWidget(right_ai)
        split.setStretchFactor(0, 0)   # 左联系人
        split.setStretchFactor(1, 1)   # 中聊天（调小）
        split.setStretchFactor(2, 2)   # 右 AI（调大）
        split.setSizes([280, 430, 660])
        root.addWidget(split, 1)
        self.statusBar().showMessage("就绪")
    def _status(self, msg):
        self.lbl_status.setText(msg)
        self.statusBar().showMessage(msg)
    def _toggle_review_panel(self):
        """展开/折叠复盘面板：AI 聊天框随之变大变小。"""
        rv = getattr(self, "review_panel", None)
        if rv is None:
            return
        show = self.btn_rv_toggle.isChecked()
        rv.setVisible(show)
        self.btn_rv_toggle.setText(
            ("\u25BC  \U0001F4DD 聊天复盘 · 笔记 · 教练报告" if show
             else "\u25B8  \U0001F4DD 聊天复盘 · 笔记 · 教练报告"))
        # 折叠时把空间让给 AI 聊天
        QtCore.QTimer.singleShot(0, lambda: self.ai_text.scrollToBottom())
    # ------------------------------------------------------------ 初始化
    def _start_init(self):
        self.btn_extract.setEnabled(False)
        self._pending = threading.Thread(target=self._init_sync, daemon=True)
        self._pending.start()
    def _init_sync(self):
        try:
            dirs = memscan.find_data_dirs()
            if not dirs:
                self._need_manual("未找到微信数据目录")
                return
            data_dir = dirs[0]
            accounts = memscan.list_accounts(data_dir)
            if not accounts:
                self._need_manual("数据目录下没有账号")
                return
            # 优先复用已解密过的账号（秒开）；都没有解密数据时再让用户选
            dec = [a for a in accounts
                   if os.path.isdir(os.path.join(DECRYPTED_DIR, a))
                   and any(os.scandir(os.path.join(DECRYPTED_DIR, a)))]
            if dec:
                account = self._pick_account(accounts, data_dir)
                self._init_done.emit(account, data_dir)
                return
            # 没有任何已解密数据：单个账号直接解，多个账号交给用户在弹窗里选
            if len(accounts) == 1:
                QtCore.QMetaObject.invokeMethod(
                    self, "_on_extract", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, accounts[0]), QtCore.Q_ARG(str, data_dir))
            else:
                QtCore.QMetaObject.invokeMethod(
                    self, "_on_extract", QtCore.Qt.ConnectionType.QueuedConnection,
                    QtCore.Q_ARG(str, ""), QtCore.Q_ARG(str, data_dir))
        except Exception as e:
            self._need_manual(str(e))
        finally:
            QtCore.QMetaObject.invokeMethod(
                self.btn_extract, "setEnabled", QtCore.Qt.ConnectionType.QueuedConnection,
                QtCore.Q_ARG(bool, True))
    def _need_manual(self, reason=""):
        QtCore.QMetaObject.invokeMethod(
            self.lbl_acc, "setText", QtCore.Qt.ConnectionType.QueuedConnection,
            QtCore.Q_ARG(str, "未找到微信数据（请手动点「提取密钥并解密」）" + (f"：{reason}" if reason else "")))
    @QtCore.Slot(str, str)
    def _on_extract(self, account=None, data_dir=None):
        if self._worker is not None and self._worker.isRunning():
            return
        if not account:
            try:
                dirs = memscan.find_data_dirs()
                if not dirs:
                    self._status("未找到微信数据目录")
                    return
                data_dir = dirs[0]
                accounts = memscan.list_accounts(data_dir)
                if not accounts:
                    self._status("数据目录下没有账号")
                    return
                if len(accounts) == 1:
                    account = accounts[0]
                else:
                    picked = self._pick_account_dialog()
                    if not picked:
                        self._status("已取消选择账号")
                        return
                    account, data_dir = picked
            except Exception as e:
                self._status(str(e))
                return
        self._status("提取密钥并解密中…")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_extract.setEnabled(False)
        self.btn_extract.setText("提取中…")
        self._worker = ExtractWorker(account, data_dir)
        self._worker.sig.log.connect(self._status)
        self._worker.sig.progress.connect(self.progress.setValue)
        self._worker.sig.done.connect(self._on_done)
        self._worker.sig.error.connect(self._on_err)
        self._worker.start()
    def _switch_account(self):
        """顶部「切换账号」：选一个账号并解密/加载它。"""
        if self._worker is not None and self._worker.isRunning():
            self._status("正在解密中，请稍候…")
            return
        picked = self._pick_account_dialog()
        if not picked:
            self._status("已取消切换账号")
            return
        account, data_dir = picked
        has_dec = (os.path.isdir(os.path.join(DECRYPTED_DIR, account))
                   and any(os.scandir(os.path.join(DECRYPTED_DIR, account))))
        if has_dec:
            self._msgs_cache.clear()
            self._load_account(account, data_dir)
            self._status(f"已切换到账号 {account}")
            return
        self._on_extract(account, data_dir)

    def _pick_account_dialog(self):
        """弹窗让用户选择要解密的微信账号（显示昵称/在线状态/解密状态）。

        本机可能登录过多个微信，只有当前登录的那个账号的密钥在内存里可提取。
        返回 (account, data_dir) 或 None（取消）。
        """
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, \
            QListWidget, QListWidgetItem, QPushButton
        self._status("正在识别账号（扫描微信内存，约需 20~60 秒）…")
        QtWidgets.QApplication.processEvents()
        try:
            infos = account_info.probe_accounts(DECRYPTED_DIR, KEYS_DIR, DATA_DIR)
        except Exception as e:
            infos = account_info.list_accounts_info(DECRYPTED_DIR, KEYS_DIR,
                                                       data_root=DATA_DIR)
            self._status(f"账号识别降级：{e}")
        if not infos:
            QtWidgets.QMessageBox.warning(self, "未找到账号", "没有找到微信账号数据目录。")
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle("选择要解密 / 查看的微信账号")
        dlg.setModal(True)
        dlg.setMinimumWidth(720)
        dlg.setStyleSheet(f"QDialog{{background:{C_BG_2};}}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        t = QLabel("选择要解密的微信账号")
        t.setStyleSheet(f"color:{C_TEXT};font-size:15px;font-weight:700;")
        lay.addWidget(t)
        tip = QLabel("勾选目标账号即可解密。已解密 / 已有密钥的账号可以随时查看；"
                     "未处理过的账号需要该微信正在登录（并打开过聊天让数据库加载）。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{C_TEXT_DIM};font-size:12px;")
        lay.addWidget(tip)
        lw = QListWidget()
        lw.setFixedHeight(340)
        lw.setWordWrap(True)
        lw.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lw.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        lw.setStyleSheet(
            f"QListWidget{{background:#ffffff;border:1px solid {C_BORDER};border-radius:9px;"
            f"padding:4px;color:{C_TEXT};font-size:13px;outline:none;}}"
            f"QListWidget::item{{padding:9px 10px;border-radius:7px;}}"
            f"QListWidget::item:selected{{background:{C_ACCENT};color:#fff;}}")
        for i in infos:
            marks = []
            if i.get("online"):
                marks.append("🟢 正在使用")
            if i.get("decrypted"):
                marks.append("✅ 已解密")
            elif i.get("can_decrypt"):
                marks.append("🗝 已有密钥，可直接解密")
            else:
                marks.append("⚠ 需登录该微信后才能解密")
            nick = i.get("nickname") or ""
            title = f"{nick}（{i['account']}）" if nick else i["account"]
            mt = i.get("mtime") or 0
            sub = ""
            if mt:
                sub += "最近使用 " + _ago_text(mt)
            if marks:
                sub += ("　" if sub else "") + "  ".join(marks)
            item = QListWidgetItem(title + "\n" + sub)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, i)
            lw.addItem(item)
        # 默认选中第一个可解密的，否则第一个
        for r in range(lw.count()):
            d = lw.item(r).data(QtCore.Qt.ItemDataRole.UserRole)
            if d.get("can_decrypt") or d.get("decrypted"):
                lw.setCurrentRow(r)
                break
        else:
            lw.setCurrentRow(0)
        lay.addWidget(lw, 1)
        btns = QHBoxLayout()
        btns.addStretch()
        b_cancel = QPushButton("取消")
        b_cancel.setStyleSheet(
            f"QPushButton{{background:transparent;color:{C_TEXT_DIM};border:1px solid {C_BORDER};"
            f"border-radius:8px;padding:7px 20px;font-size:13px;}}")
        b_cancel.clicked.connect(dlg.reject)
        b_ok = QPushButton("解密这个账号")
        b_ok.setStyleSheet(
            f"QPushButton{{background:{C_ACCENT};color:#fff;border:0;border-radius:8px;"
            f"padding:8px 22px;font-size:13px;font-weight:600;}}"
            f"QPushButton:hover{{background:{C_ACCENT_2};}}")
        b_ok.clicked.connect(dlg.accept)
        btns.addWidget(b_cancel)
        btns.addWidget(b_ok)
        lay.addLayout(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        sel = lw.currentItem()
        if not sel:
            return None
        d = sel.data(QtCore.Qt.ItemDataRole.UserRole)
        return (d["account"], d["data_dir"])

    @staticmethod
    def _pick_account(accounts: list, data_dir: str) -> str:
        """选择要提取的账号：优先当前微信登录的账号（db_storage 最新修改 = 正在使用）。
        数据目录里可能有多台设备/历史账号，只有当前登录账号的密钥能在内存中匹配到。
        """
        # 1) 已有解密数据优先（上次用过）
        dec = [a for a in accounts
               if os.path.isdir(os.path.join(DECRYPTED_DIR, a))
               and any(list(os.scandir(os.path.join(DECRYPTED_DIR, a))))]
        if dec:
            return dec[0]
        # 2) 否则取 db_storage 目录 mtime 最新的（当前登录的账号在实时写）
        def _mtime(a):
            p = os.path.join(data_dir, a, "db_storage")
            try:
                return os.path.getmtime(p)
            except OSError:
                return 0.0
        return max(accounts, key=_mtime)
    def _on_done(self, res):
        self.progress.setVisible(False)
        self.btn_extract.setEnabled(True)
        self.btn_extract.setText("提取密钥并解密")
        self._status("解密完成 ✓")
        account = res.get("account") or self._worker.account
        data_dir = self._worker.data_dir
        self._load_account(account, data_dir)
    def _on_err(self, msg):
        self.progress.setVisible(False)
        self.btn_extract.setEnabled(True)
        self.btn_extract.setText("提取密钥并解密")
        self._status("解密失败：" + str(msg))
        # 密钥提取失败是最常见问题，弹窗给出明确的操作指引
        if "密钥" in str(msg) or "登录" in str(msg):
            QtWidgets.QMessageBox.warning(
                self, "解密失败 · 怎么解决",
                "没找到这个账号的密钥。\n\n"
                "请确认：\n"
                "1. 你要看的那个微信**正登录着**（不是其它微信）；\n"
                "2. 登录后随便点开一个聊天窗口，让数据库加载进内存；\n"
                "3. 再点一次「提取密钥并解密」。\n\n"
                "如果本机登录过多个微信，请点顶部「切换账号 / 选择账号」手动选目标账号。")
    def _account_label(self, account: str) -> str:
        """顶栏显示：昵称（wxid），没有昵称就只显示 wxid。"""
        nick = account_info._self_nickname(DECRYPTED_DIR, account)
        if not nick:
            nick = account_info.load_nickname_cache(DATA_DIR).get(account, "")
        if nick:
            account_info.save_nickname(DATA_DIR, account, nick)
        return f"账号：{nick}（{account}）" if nick else f"账号：{account}"

    def _check_runtime_deps(self) -> str:
        """运行期依赖自检：zstandard 缺失会导致压缩消息显示乱码/缺字，提前告警。"""
        try:
            from backend.core.models import ZSTD_AVAILABLE, ZSTD_MISSING_REASON
            if not ZSTD_AVAILABLE:
                return ZSTD_MISSING_REASON + "；请执行 .venv\\Scripts\\python.exe -m pip install zstandard"
        except Exception as e:
            return f"依赖自检失败：{e}"
        return ""
    # ------------------------------------------------------------ 加载账号
    def _load_account(self, account: str, data_dir: str):
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
        self.account = account
        self.lbl_acc.setText(self._account_label(account))
        # 注入长期记忆：账号变化时清掉旧会话，让记忆按账号隔离
        if self.ai.account != account:
            self.ai.sessions.clear()
            self._ai_loading_session = True
            try:
                self.ai_chat_model.clear()
                self.cmb_ai_session.blockSignals(True)
                self.cmb_ai_session.clear()
            finally:
                self.cmb_ai_session.blockSignals(False)
                self._ai_loading_session = False
        self.ai.account = account
        self.ai.memory_store = buddy_memory
        # 运行期依赖自检：zstandard 缺失时压缩消息会显示乱码/缺字，这里明确提示
        _warn = self._check_runtime_deps()
        if _warn and not getattr(self, "_deps_warned", False):
            self._deps_warned = True
            self._status("⚠ " + _warn)
        self.store = Store(DECRYPTED_DIR, account)
        # 常驻媒体库：解析 cache 明文图（微信里打开过的图片可直接显示）
        try:
            from backend.core.media import MediaStore
            from backend.core import memscan as _ms
            _src = None
            for _d in _ms.find_data_dirs():
                if os.path.isdir(os.path.join(_d, account)):
                    _src = os.path.join(_d, account)
                    break
            self._media_store = MediaStore(account, DECRYPTED_DIR, KEYS_DIR, _src) if _src else None
            if self._media_store:
                # 用字节解析器：wxgf/hevc 会自动转成 JPEG，桌面才能显示
                self.chat_model.set_image_bytes_resolver(self._media_store.load_displayable_image)
        except Exception:
            self._media_store = None
        self._contacts_loading = False
        self._refresh_contacts()
        keyfile = os.path.join(KEYS_DIR, f"{account}.json")
        storage = os.path.join(data_dir, account, "db_storage")
        if os.path.isdir(storage) and os.path.isfile(keyfile):
            self.watcher = ChatWatcher(
                account, DECRYPTED_DIR, storage, keyfile,
                on_update=lambda talkers: self._on_new_messages(list(talkers)), poll_interval=2.0)
            self.watcher.start()
            self._status("实时监听已开启（微信新消息自动刷新）")
    def _refresh_contacts(self, incremental: bool = False):
        """刷新联系人列表。
        incremental=True（新消息时）：保留现有列表，只异步重算计数后整体替换数据
        （不重置 model 也能用 set_items 全量替换，但避免重复查 contacts()）。
        """
        if self.store is None or self._contacts_loading:
            return
        if incremental and self._contact_display:
            # 已有列表：只重算计数（contacts()/known_talkers 已缓存，代价低）
            self._recount_async()
            return
        self._contacts_loading = True
        self._contact_display = []
        self._alias_map = {}
        for c in self.store.contacts():
            self._contact_display.append((c["username"], c.get("display") or c["username"], 0))
            self._alias_map[c["username"]] = c.get("alias") or ""
        known = self.store.known_talkers()
        seen = {u for u, _d, _c in self._contact_display}
        for u in sorted(known - seen):
            self._contact_display.append((u, u, 0))
            self._alias_map.setdefault(u, "")
        self._render_contacts()
        self._status("加载消息数量…")
        def wait():
            try:
                self._pending_counts = self.store.counts_map()
            except Exception:
                self._pending_counts = {}
            QtCore.QMetaObject.invokeMethod(self, "_apply_counts",
                                            QtCore.Qt.ConnectionType.QueuedConnection)
        threading.Thread(target=wait, daemon=True).start()
    def _recount_async(self):
        """增量重算计数：异步，不碰 model（完成后整体替换数据）。"""
        if self._pending_counts is not None:
            return  # 已有一次在算
        def wait():
            try:
                self._pending_counts = self.store.counts_map()
            except Exception:
                self._pending_counts = {}
            QtCore.QMetaObject.invokeMethod(self, "_apply_counts",
                                            QtCore.Qt.ConnectionType.QueuedConnection)
        threading.Thread(target=wait, daemon=True).start()
    @QtCore.Slot()
    def _apply_counts(self):
        cm = self._pending_counts or {}
        self._pending_counts = None
        if self.store is None:
            return
        newd = []
        for u, d, _c in self._contact_display:
            newd.append((u, d, cm.get(u, 0)))
        self._contact_display = newd
        self._render_contacts()
        self._contacts_loading = False
        self._status(f"联系人 {len(newd)} 个，选中左侧查看聊天（新消息自动刷新）")
    def _render_contacts(self):
        items = sorted(self._contact_display, key=lambda x: -x[2])
        kw = self.search_edit.text().strip().lower()
        if kw:
            items = [it for it in items
                     if kw in it[0].lower() or kw in (it[1] or "").lower()
                     or kw in self._alias_map.get(it[0], "").lower()]
        self.contact_model.set_items(items)

    def _filter_contacts(self, _text):
        """搜索框输入时实时过滤联系人列表。"""
        if self.store is None:
            return
        # 保留当前选中（若被过滤掉则清掉）
        self._render_contacts()
        sel = self.contact_list.selectionModel()
        cur = sel.currentIndex() if sel else QtCore.QModelIndex()
        if cur.isValid():
            cur_t = self.contact_model.talker_at(cur.row())
            if cur_t and self._cur_talker == cur_t:
                pass  # 当前聊天保留
        self._status(f"搜索到 {self.contact_model.rowCount()} 个联系人" if self.search_edit.text().strip()
                     else f"联系人 {len(self._contact_display)} 个")

    def _on_contact_clicked(self, index):
        u = self.contact_model.talker_at(index.row())
        if u:
            self._show_chat(u)
    def _show_chat(self, talker: str):
        if self.store is None:
            return
        # 切走前保存旧联系人的 AI 会话（消息 + 补充场景，含未发送的输入）
        if self._cur_talker and self._cur_talker != talker and self.account is not None:
            self._save_ai_conversation()
        display = next((d for u, d, _c in self._contact_display if u == talker), talker)
        self._cur_talker = talker
        self._cur_peer = display
        self._setup_ai_panel()
        self._load_review()
        # 不自动分析：用户点击「🤖 让 AI 分析这段聊天」后才触发全量分析
        # 消息缓存命中 → 直接渲染（秒开）；否则后台线程读，UI 不卡
        cached = self._msgs_cache.get(talker)
        if cached is not None:
            self._render_msgs(talker, display, cached)
            return
        # 先显示占位，后台读取
        self.chat_head.setText(f"  {display}　（加载中…）")
        self.chat_model.set_messages([], talker.endswith("@chatroom"))
        self._status(f"加载 {display} 的消息…")
        def load():
            try:
                msgs = self.store.messages(talker)
            except Exception:
                msgs = []
            # 缓存（上限防止内存膨胀）
            if len(self._msgs_cache) > 60:
                self._msgs_cache.clear()
            self._msgs_cache[talker] = msgs
            QtCore.QMetaObject.invokeMethod(self, "_show_chat_done",
                                            QtCore.Qt.ConnectionType.QueuedConnection,
                                            QtCore.Q_ARG(str, talker), QtCore.Q_ARG(str, display))
        threading.Thread(target=load, daemon=True).start()
    @QtCore.Slot(str, str)
    def _show_chat_done(self, talker: str, display: str):
        if self._cur_talker != talker:
            return  # 用户已切换走，忽略
        self._render_msgs(talker, display, self._msgs_cache.get(talker, []))
    def _render_msgs(self, talker: str, display: str, msgs: list, scroll: bool = True):
        # 虚拟化：直接把全部消息丢给 model（几万条也不卡），delegate 只画可见行
        is_group = talker.endswith("@chatroom")
        # 记录滚动位置（增量更新时保持）
        sb = self.chat_view.verticalScrollBar()
        was_at_bottom = sb.value() >= sb.maximum() - 20
        self.chat_model.set_messages(msgs, is_group)
        self._cur_msgs = msgs
        self.chat_head.setText(f"  {display}　（{len(msgs)} 条）")
        self._status(f"{display}：共 {len(msgs)} 条")
        # 滚到底部（仅切换聊天时）；增量刷新时：若本来在底部则跟随到底，否则保持位置
        if scroll:
            QtCore.QTimer.singleShot(60, lambda: self.chat_view.scrollToBottom())
        else:
            if was_at_bottom:
                QtCore.QTimer.singleShot(60, lambda: self.chat_view.scrollToBottom())
            # 否则不动滚动条（用户在看历史，不打扰）
    # ------------------------------------------------------------ 复盘（笔记/AI）
    def _load_review(self):
        """切换聊天时加载：笔记、星标/重要消息、AI 可用性。"""
        if not self._cur_talker or self.account is None:
            return
        t = self._cur_talker
        note = notes_mod.get_chat_note(self.account, t)
        self.rv_note.setText(note)
        # 有笔记的消息高亮变色
        try:
            self.chat_model.set_noted(notes_mod.note_mids(self.account, t))
        except Exception:
            pass
        # 收集星标 + 有笔记的消息
        star_msgs: list[tuple[str, dict, dict]] = []
        for mid, info in notes_mod.starred(self.account, t):
            for m in self._cur_msgs:
                if m.get("mid") == mid:
                    star_msgs.append((mid, info, m))
                    break
        for mid, info in notes_mod.noted(self.account, t):
            if any(sm[0] == mid for sm in star_msgs):
                continue
            for m in self._cur_msgs:
                if m.get("mid") == mid:
                    star_msgs.append((mid, info, m))
                    break
        parts = []
        if note:
            parts.append(f"📝 聊天笔记：{note}")
        if star_msgs:
            parts.append("\n⭐ 重要消息 / 笔记：")
            for mid, info, m in star_msgs[:20]:
                who = "我" if m.get("is_self") else (m.get("sender") or "对方")
                txt = (m.get("text") or "")[:40].replace("\n", " ")
                star_mark = "★" if info.get("star") else "✎"
                parts.append(f"  {star_mark} [{m.get('time','')[:16]}] {who}: {txt}"
                             + (f"｜{info['note']}" if info.get("note") else ""))
        if not parts:
            parts.append("（这个聊天还没有笔记。右键任意消息可「标为重要」或「写笔记」，"
                         "上方可写整段聊天笔记，或点「✨ AI 一键复盘」自动总结。）")
        self.rv_text.setPlainText("\n".join(parts))
        # AI 复盘按钮可用性
        self.btn_rv_ai.setEnabled(self.ai.enabled() and len(self._cur_msgs) > 0)
        # 导出复盘按钮：有当前聊天即可用（导出当前聊天或全部）
        self.btn_rv_export.setEnabled(self._cur_talker is not None)

    # ------------------------------------------------------------ 消息右键（标星/笔记）

    def _chat_menu(self, pos):
        """聊天区右键菜单：单条写/删笔记，多选批量写笔记/标星/删笔记。"""
        idx = self.chat_view.indexAt(pos)
        if not idx.isValid():
            return
        m = idx.data(QtCore.Qt.ItemDataRole.UserRole)
        if not m or not m.get("mid"):
            return
        from PySide6.QtWidgets import QMenu, QMessageBox
        acc = self.account
        talker = self._cur_talker or ""
        menu = QMenu(self)

        # 收集选中的消息（右键行若不在选区里，则只作用于该行）
        selected = [i.data(QtCore.Qt.ItemDataRole.UserRole)
                    for i in self.chat_view.selectedIndexes()]
        sel_mids = [x["mid"] for x in selected if x and x.get("mid")]
        if m["mid"] not in sel_mids:
            sel_mids = [m["mid"]]
        multi = len(sel_mids) > 1

        if multi:
            menu.addAction(f"已选中 {len(sel_mids)} 条消息").setEnabled(False)
            menu.addSeparator()
            act_note_all = menu.addAction(f"✎ 给这 {len(sel_mids)} 条写同一份笔记")
            act_star_all = menu.addAction(f"★ 把这 {len(sel_mids)} 条标为重要")
            act_unstar_all = menu.addAction(f"☆ 取消这 {len(sel_mids)} 条的星标")
            menu.addSeparator()
            act_del_all = menu.addAction(f"🗑 删除这 {len(sel_mids)} 条的笔记")
            act = menu.exec(self.chat_view.mapToGlobal(pos))
            if act is None:
                return
            if act == act_note_all:
                n = notes_mod.set_messages_batch(acc, talker, sel_mids,
                                                  note=self._ask_note_text("给选中的多条消息写笔记"))
            elif act == act_star_all:
                n = notes_mod.set_messages_batch(acc, talker, sel_mids, star=True)
            elif act == act_unstar_all:
                n = notes_mod.set_messages_batch(acc, talker, sel_mids, star=False)
            elif act == act_del_all:
                n = notes_mod.delete_notes_batch(acc, talker, sel_mids)
                self._status(f"已删除 {n} 条笔记" if n else "选中的消息没有笔记")
            else:
                return
            self._after_note_change(f"已更新 {n} 条" if n else "没有变化")
            return

        # 单条
        mid = m["mid"]
        info = notes_mod.get_message(acc, talker, mid) if acc else None
        star = bool(info and info.get("star"))
        note = (info or {}).get("note", "") if info else ""
        act_star = menu.addAction("★ 标为重要" if not star else "☆ 取消星标")
        act_note = menu.addAction("✎ 写笔记" if not note else "✎ 编辑笔记")
        act_del = menu.addAction("🗑 删除笔记") if note else None
        act_view = menu.addAction("📖 查看笔记") if note else None
        act = menu.exec(self.chat_view.mapToGlobal(pos))
        if act is None:
            return
        if act == act_star:
            notes_mod.set_message(acc, talker, mid, star=not star)
            self._load_review()
        elif act == act_note:
            self._edit_msg_note(mid, note)
        elif act_del is not None and act == act_del:
            notes_mod.delete_notes_batch(acc, talker, [mid])
            self._after_note_change("已删除笔记")
        elif act_view is not None and act == act_view:
            QMessageBox.information(self, "消息笔记", note)

    def _ask_note_text(self, title: str, cur: str = "") -> str:
        from PySide6.QtWidgets import QInputDialog, QTextEdit, QDialog, QDialogButtonBox, QVBoxLayout, QLabel
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("笔记内容（留空则不保存）："))
        ed = QTextEdit(dlg)
        ed.setPlainText(cur)
        ed.setMinimumSize(380, 150)
        lay.addWidget(ed)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec():
            return ed.toPlainText().strip()
        return None

    def _after_note_change(self, msg: str = ""):
        """笔记/星标变更后：刷新高亮 + 右侧复盘面板。"""
        if msg:
            self._status(msg)
        if self.account and self._cur_talker:
            try:
                self.chat_model.set_noted(notes_mod.note_mids(self.account, self._cur_talker))
            except Exception:
                pass
        self._load_review()

    def _edit_msg_note(self, mid: str, cur: str = ""):
        if not self.account or not self._cur_talker:
            return
        from PySide6.QtWidgets import (QTextEdit, QDialog,
                                       QDialogButtonBox, QVBoxLayout, QLabel)
        dlg = QDialog(self)
        dlg.setWindowTitle("消息笔记")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("给这条消息写笔记/评价："))
        ed = QTextEdit(dlg)
        ed.setPlainText(cur)
        ed.setMinimumSize(360, 140)
        lay.addWidget(ed)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec():
            notes_mod.set_message(self.account, self._cur_talker, mid, note=ed.toPlainText().strip())
            self._after_note_change("笔记已保存")

    def _save_chat_note(self):
        if not self._cur_talker or self.account is None:
            return
        notes_mod.set_chat_note(self.account, self._cur_talker, self.rv_note.text().strip())
        self._status("聊天笔记已保存")
        self._load_review()
    def _manual_review(self):
        """AI 一键教练报告：后台线程生成，完成后显示。"""
        if not self._cur_talker or not self.ai.enabled():
            self._status("请先配置 AI 密钥")
            return
        if self._rv_gen is not None and self._rv_gen.is_alive():
            return
        talker = self._cur_talker
        msgs = self.store.messages(talker)
        extra = self._ai_extra_context()
        self.rv_text.setPlainText("AI 正在生成教练报告，请稍候…（较大聊天可能需要 30-90 秒）")
        def task():
            try:
                text = self.ai.review(talker, msgs, timeout=120, extra_context=extra)
            except Exception as e:
                err = friendly_error(e)
                QtCore.QMetaObject.invokeMethod(self, "_review_done",
                                                QtCore.Qt.ConnectionType.QueuedConnection,
                                                QtCore.Q_ARG(str, ""), QtCore.Q_ARG(str, err))
                return
            QtCore.QMetaObject.invokeMethod(self, "_review_done",
                                            QtCore.Qt.ConnectionType.QueuedConnection,
                                            QtCore.Q_ARG(str, text or "（AI 返回为空）"), QtCore.Q_ARG(str, ""))
        self._rv_gen = threading.Thread(target=task, daemon=True)
        self._rv_gen.start()
    @QtCore.Slot(str, str)
    def _review_done(self, text: str, err: str):
        if err:
            self.rv_text.setPlainText(f"⚠ 教练报告生成失败：{err}")
            return
        self.rv_text.setPlainText(f"✨ 教练报告：\n\n{text}")
    # ------------------------------------------------------------ 导出复盘 / 搜笔记
    def _export_review(self):
        """导出当前聊天（或全部）标星/有笔记的消息为复盘文档（HTML/MD 二选一）。"""
        if self.account is None:
            return
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        # 选择格式
        fmt, _ = QFileDialog.getSaveFileName(
            self, "导出复盘文档", "复盘笔记.html",
            "HTML 文档 (*.html);;Markdown (*.md)")
        if not fmt:
            return
        try:
            md = notes_mod.export_review_markdown(
                self.account, self.store, talker=self._cur_talker or None,
                keyword=self.srch_edit.text().strip() or None)
            if fmt.endswith(".md"):
                with open(fmt, "w", encoding="utf-8") as f:
                    f.write(md)
            else:
                html = notes_mod.export_review_html(md, "聊天复盘笔记")
                with open(fmt, "w", encoding="utf-8") as f:
                    f.write(html)
            self._status(f"复盘文档已导出：{os.path.basename(fmt)}")
            QMessageBox.information(self, "导出成功", f"已保存到：\n{fmt}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))
    def _search_notes(self):
        """跨聊天搜索笔记/星标，结果显示在复盘区。"""
        if self.account is None:
            return
        kw = self.srch_edit.text().strip()
        items = notes_mod.search(self.account, kw)
        if not items:
            self.rv_text.setPlainText(f"（没有找到{'关键词「' + kw + '」' if kw else ''}相关的笔记/星标）")
            return
        # 补消息原文
        lines = [f"🔍 搜索到 {len(items)} 条笔记/星标" + (f"（关键词：{kw}）" if kw else "") + "：", ""]
        # 快速查文本：按 talker 分组一次取消息
        cache: dict[str, dict] = {}
        for it in items:
            t = it["talker"]
            if t not in cache and self.store:
                try:
                    cache[t] = {m["mid"]: m for m in self.store.messages(t)}
                except Exception:
                    cache[t] = {}
            mm = cache.get(t, {}).get(it["mid"])
            who = "我" if (mm and mm.get("is_self")) else "对方"
            txt = (mm.get("text") if mm else "") or ""
            txt = str(txt).replace("\n", " ")[:60]
            display = self.store.display_name(t) if self.store else t
            mark = "★" if it["star"] else "✎"
            when = _ts(it.get("updated", 0))
            lines.append(f"{mark} [{display}] {who}：{txt}　{when}")
            if it["note"]:
                lines.append(f"   笔记：{it['note']}")
        self.rv_text.setPlainText("\n".join(lines))
    # ------------------------------------------------------------ AI 建议 / 对话
    def _setup_ai_panel(self):
        """切换联系人/配置时刷新 AI 面板：加载该联系人的 AI 会话（历史 + 补充场景）。"""
        enabled = self.ai.enabled()
        ok = enabled and self._cur_talker is not None
        self.btn_ai_send.setEnabled(ok)
        self.btn_ai_analyze.setEnabled(ok)
        if not enabled:
            self._refresh_ai_session_list()
            self.btn_ai_analyze.setEnabled(False)
            self.ai_chat_model.clear()
            self.ai_chat_model.add({"who": "sys", "text": "未启用（点右上 ⚙ AI 配置 API 密钥）"})
            self.ai_status.setText("")
            return
        if self._cur_talker is None:
            self._refresh_ai_session_list()
            self.ai_chat_model.clear()
            self.ai_chat_model.add({"who": "sys", "text": "✓ AI 已启用。请在左侧选择一个联系人，"
                                   "然后点「🤖 让 AI 分析这段聊天」开始。"})
            self.ai_status.setText("")
            return
        # 加载当前联系人的 AI 会话（不重载已选中的会话语义：仅当模型为空或联系人变化时）
        if self._ai_loading_session:
            return
        self._load_ai_conversation(self._cur_talker)
        self.ai_status.setText("")
        if self.ai_chat_model.rowCount() == 0:
            self.ai_chat_model.add({"who": "sys", "text":
                "💬 和 AI 对话：点击上方「🤖 让 AI 分析这段聊天」先把这段聊天的全量记录交给恋爱教练分析；"
                "之后在下方输入框继续追问。也可以让对方发新消息，AI 自动给出回复方案。"})

    def _ai_ctx_built(self, talker: str) -> bool:
        return bool(getattr(self, "_ai_ctx_talkers", set())) and talker in self._ai_ctx_talkers

    def _mark_ai_ctx_built(self, talker: str) -> None:
        s = getattr(self, "_ai_ctx_talkers", None)
        if s is None:
            s = set()
            self._ai_ctx_talkers = s
        s.add(talker)

    def _ai_conv_title(self, talker: str) -> str:
        """会话条显示名：优先自定义标题，其次联系人显示名。"""
        if self.account is None:
            return talker
        pop = {}
        try:
            pop = ai_chats.load_conversation(self.account, talker)
        except Exception:
            pass
        title = (pop.get("title") or "").strip()
        if title:
            return title
        try:
            d = self.store.display_name(talker) if self.store else ""
        except Exception:
            d = ""
        return d or talker

    def _refresh_ai_session_list(self, select_talker: str | None = None):
        """重建会话下拉框：当前账号下所有已有 AI 会话 + 当前联系人（没有则加「新会话」）。"""
        target = select_talker or self._cur_talker
        entries: list[tuple[str, str]] = []  # (talker, display)
        seen: set[str] = set()
        if self.account is not None:
            try:
                for c in ai_chats.list_conversations(self.account):
                    entries.append((c["talker"], self._ai_conv_title(c["talker"])))
                    seen.add(c["talker"])
            except Exception:
                pass
        if target and target not in seen:
            entries.append((target, self._ai_conv_title(target)))
        if self.account is None and target is None:
            entries = []
        # 按显示名排序（当前会话排最前，方便找到）
        if target:
            entries.sort(key=lambda x: (x[0] != target, x[1].lower()))
        self._ai_session_talkers = [t for t, _d in entries]
        self._ai_loading_session = True
        try:
            self.cmb_ai_session.blockSignals(True)
            self.cmb_ai_session.clear()
            for _t, d in entries:
                self.cmb_ai_session.addItem(d)
            if target is not None:
                idx = self._ai_session_talkers.index(target) if target in self._ai_session_talkers else 0
                self.cmb_ai_session.setCurrentIndex(max(0, idx))
            self.btn_ai_sess_rename.setEnabled(target is not None)
            self.btn_ai_sess_clear.setEnabled(target is not None)
            self.btn_ai_sess_del.setEnabled(target is not None)
        finally:
            self.cmb_ai_session.blockSignals(False)
            self._ai_loading_session = False

    def _load_ai_conversation(self, talker: str):
        """载入某联系人的 AI 会话到界面（历史消息 + 补充场景），并选中下拉项。"""
        self._refresh_ai_session_list(select_talker=talker)
        msgs: list[dict] = []
        extra = ""
        if self.account is not None:
            try:
                pop = ai_chats.load_conversation(self.account, talker)
                msgs = [dict(m) for m in pop.get("messages") or []]
                extra = pop.get("extra_context") or ""
            except Exception:
                msgs, extra = [], ""
        self._ai_loading_session = True
        try:
            self.ai_chat_model.set_items(msgs)
            # 恢复该联络人的补充场景（不在聊天记录里的背景）
            if self.ai_extra.toPlainText().strip() != extra.strip():
                self.ai_extra.setPlainText(extra)
            # 已填过补充场景时自动展开，方便看到该会话的背景信息
            self.btn_ai_extra_toggle.setChecked(bool(extra.strip()))
            self.ai_extra.setVisible(bool(extra.strip()))
        finally:
            self._ai_loading_session = False
        # 回填 AI 侩文上下文：切换会话/重启后还要让模型看得到之前的问答
        if msgs:
            try:
                s = self.ai.session_for(talker, self._cur_peer or talker)
                s.restore_history(msgs, extra_context=extra)
                # 已有历史则不得再重建，否则会流失
                if s.history:
                    self._mark_ai_ctx_built(talker)
            except Exception:
                pass
        self.ai_text.scrollToBottom()

    def _save_ai_conversation(self):
        """把当前 AI 面板（消息 + 补充场景）持久化到当前联系人会话。"""
        if self.account is None or not self._cur_talker:
            return
        msgs = []
        for i in range(self.ai_chat_model.rowCount()):
            it = self.ai_chat_model.data(self.ai_chat_model.index(i, 0),
                                         QtCore.Qt.ItemDataRole.UserRole) or {}
            if it.get("who") in ("me", "ai") and it.get("text"):
                msgs.append({"who": it["who"], "text": it["text"]})
        try:
            ai_chats.save_conversation(
                self.account, self._cur_talker, msgs,
                extra_context=self._ai_extra_context())
        except Exception:
            pass

    def _on_ai_session_switch(self, idx: int):
        """下拉切换：保存当前会话 → 切到目标联系人的界面与 AI 会话。"""
        if self._ai_loading_session or idx < 0:
            return
        talkers = getattr(self, "_ai_session_talkers", [])
        if idx >= len(talkers):
            return
        self._save_ai_conversation()
        target = talkers[idx]
        if target and target != self._cur_talker:
            self._show_chat(target)

    def _ai_sess_rename(self):
        if not self._cur_talker or self.account is None:
            return
        cur = self._ai_conv_title(self._cur_talker)
        title, ok = QtWidgets.QInputDialog.getText(
            self, "重命名会话", "给这个 AI 会话起个名字（留空恢复默认）：", text=cur)
        if not ok or self._cur_talker is None:
            return
        try:
            ai_chats.rename_conversation(self.account, self._cur_talker, title)
        except Exception as e:
            self._status(f"重命名失败：{e}")
            return
        self._save_ai_conversation()
        self._refresh_ai_session_list(select_talker=self._cur_talker)
        self._status("会话已重命名")

    def _ai_sess_clear(self):
        """清空当前会话的消息（保留补充场景），并重置 AI 上下文字段。"""
        if not self._cur_talker or self.account is None:
            return
        ret = QtWidgets.QMessageBox.question(
            self, "清空会话", "清空这个 AI 会话的全部对话（保留补充场景）？\nAI 的上下文也会重置。",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if ret != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            ai_chats.clear_messages(self.account, self._cur_talker)
        except Exception:
            pass
        self.ai.reset_session(self._cur_talker)
        getattr(self, "_ai_ctx_talkers", set()).discard(self._cur_talker)
        self.ai_chat_model.clear()
        self.ai_chat_model.add({"who": "sys", "text":
            "🧹 会话已清空。点「🤖 让 AI 分析这段聊天」重新开始。"})
        self._save_ai_conversation()
        self.ai_status.setText("")
        self._status("AI 会话已清空")

    def _ai_sess_delete(self):
        """删除当前会话（消息 + 补充场景 + AI 上下文全部删除）。"""
        if not self._cur_talker or self.account is None:
            return
        ret = QtWidgets.QMessageBox.question(
            self, "删除会话",
            f"确定删除「{self._ai_conv_title(self._cur_talker)}」的 AI 会话吗？\n"
            "删除后消息、补充场景和 AI 上下文都会清掉，且无法恢复。",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if ret != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            ai_chats.delete_conversation(self.account, self._cur_talker)
        except Exception:
            pass
        self.ai.reset_session(self._cur_talker)
        getattr(self, "_ai_ctx_talkers", set()).discard(self._cur_talker)
        self.ai_chat_model.clear()
        self.ai_chat_model.add({"who": "sys", "text":
            "🗑 会话已删除。点「🤖 让 AI 分析这段聊天」重新开始。"})
        self.ai_extra.clear()
        self._refresh_ai_session_list(select_talker=self._cur_talker)
        self.ai_status.setText("")
        self._status("AI 会话已删除")
    def _copy_suggest(self):
        rows = self.ai_chat_model.rowCount()
        txt = ""
        for i in range(rows):
            it = self.ai_chat_model.data(self.ai_chat_model.index(i, 0),
                                         QtCore.Qt.ItemDataRole.UserRole) or {}
            if it.get("who") == "ai":
                txt = it.get("text") or ""
        if not txt:
            self._status("还没有可复制的建议")
            return
        QtWidgets.QApplication.clipboard().setText(txt)
        self._status("已复制到剪贴板（可到微信里粘贴发送）")
    def _open_ai_settings(self):
        dlg = AISettingsDialog(self.ai.cfg, self)
        if dlg.exec():
            self.ai.update_config(
                api_url=dlg.cfg.get("api_url", ""),
                api_key=dlg.cfg.get("api_key", ""),
                model=dlg.cfg.get("model", "deepseek-chat"),
                max_context_msgs=int(dlg.cfg.get("max_context_msgs", 80)),
                persona=dlg.cfg.get("persona", ""),
                analysis_task=dlg.cfg.get("analysis_task", ""),
                enabled=bool(dlg.cfg.get("enabled")),
                auto_copy=bool(dlg.cfg.get("auto_copy")),
            )
            # 配置变化 → 重置已有会话（强制下次全量重建，新人格底色生效）
            self.ai.sessions.clear()
            self._setup_ai_panel()
            self._status("AI 配置已保存")
    def _manual_ai(self):
        if not self._cur_talker or not self.ai.enabled():
            self._status("请先配置 AI 密钥")
            return
        self._gen_ai(force=True)
    def _gen_ai(self, force: bool = False, first_open: bool = False):
        if self._cur_talker is None or not self.ai.enabled():
            return
        if self.ai_gen is not None and self.ai_gen.is_alive():
            return
        self._ai_first_pending = first_open  # 标记本次是首次分析
        talker = self._cur_talker
        peer = self._cur_peer or talker
        # 分析/建议都用带跳动圆点的 AI 气泡，避免页面呆滞
        self.ai_chat_model.add({"who": "sys", "text":
            "AI 正在通读全量聊天记录（谁说的、几点发的）…" if first_open else "AI 正在思考…"})
        self.ai_chat_model.add({"who": "ai", "text": "", "streaming": True, "thinking": True})
        self._start_thinking_anim()
        if first_open:
            self.ai_status.setText("先让 AI 整体分析，之后对方新消息会自动出方案")
        else:
            self.ai_status.setText("正在生成 3 个回复方案")
        def task():
            try:
                # 消息读取放后台线程，不阻塞主线程（读大群很耗时）
                msgs = self.store.messages(talker) if self.store else []
                text = self.ai.suggest(talker, msgs, peer, force_rebuild=force)
                # 分析已经把聊天记录灌进去了，后续追问直接沿用
                self._mark_ai_ctx_built(talker)
            except Exception as e:
                text = None
                err = friendly_error(e)
                QtCore.QMetaObject.invokeMethod(self, "_ai_done",
                                                QtCore.Qt.ConnectionType.QueuedConnection,
                                                QtCore.Q_ARG(str, ""), QtCore.Q_ARG(str, err))
                return
            QtCore.QMetaObject.invokeMethod(self, "_ai_done",
                                            QtCore.Qt.ConnectionType.QueuedConnection,
                                            QtCore.Q_ARG(str, text or ""), QtCore.Q_ARG(str, ""))
        self.ai_gen = threading.Thread(target=task, daemon=True)
        self.ai_gen.start()

    # ---- 与 AI 自由对话（分析聊天记录）----
    def _ai_extra_context(self) -> str:
        """读取用户在 AI 面板补充的场景（不在聊天记录里的信息）。"""
        try:
            return (self.ai_extra.toPlainText() or "").strip()
        except Exception:
            return ""
    def eventFilter(self, obj, event):
        """QTextEdit 里 Ctrl+Enter 发送，Enter 换行。"""
        if obj is self.ai_input and event.type() == QtCore.QEvent.Type.KeyPress:
            if (event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier
                    and event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter)):
                self._send_ai_msg()
                return True
        return super().eventFilter(obj, event)

    def _send_ai_msg(self):
        """用户在对话窗口输入 → AI 流式回答（打字机效果），追加显示。"""
        q = self.ai_input.toPlainText().strip()
        if not q or not self._cur_talker or not self.ai.enabled():
            self._status("请先配置 AI 密钥")
            return
        if self.ai_gen is not None and self.ai_gen.is_alive():
            return
        self.ai_input.clear()
        self._append_ai_chat("👤 我", q)
        talker = self._cur_talker
        self._ai_stream_talker = talker   # 流式期间若切换联系人，禁止把增量写进新会话
        self._ai_stream_q = q             # 保留本轮问题（切走后离线保存用）
        peer = self._cur_peer or talker
        extra = self._ai_extra_context()
        # 追加一个「AI 思考中」占位，流式开始后原地填充
        self.ai_chat_model.add({"who": "ai", "text": "", "streaming": True, "thinking": True})
        self._start_thinking_anim()
        self.ai_status.setText("AI 思考中…" + ("（含你补充的场景）" if extra else ""))
        self.btn_ai_send.setEnabled(False)

        # 跨线程：worker 把增量文本塞进队列，UI 定时器取走追加
        import queue
        self._ai_delta_q = queue.Queue()
        self._ai_done_holder = {"err": "", "ok": False, "text": ""}

        def on_delta(delta):
            try:
                self._ai_delta_q.put_nowait(delta)
            except Exception:
                pass

        def task():
            try:
                msgs = self.store.messages(talker) if self.store else []
                # 只有首次进入这个会话（或重建后）才重新灌入聊天记录；
                # 之后的追问直接沿用上下文，否则 AI 永远不知道上一句说了什么
                force_ctx = not self._ai_ctx_built(talker)
                answer = self.ai.chat(
                    talker, msgs, peer, user_msg=q, force_context=force_ctx,
                    extra_context=extra, on_delta=on_delta, stream=True)
                self._mark_ai_ctx_built(talker)
                self._ai_done_holder["ok"] = True
                self._ai_done_holder["text"] = answer or ""
            except Exception as e:
                self._ai_done_holder["err"] = friendly_error(e)
            finally:
                self._ai_delta_q.put_nowait("__DONE__")
                # 流式结束：把完整 AI 回答写回模型并持久化（worker 线程仅写队列，
                # 模型/磁盘操作走主线程由 _ai_stream_tick 完成）

        self._ai_stream_timer = QtCore.QTimer(self)
        self._ai_stream_timer.setInterval(30)
        self._ai_stream_timer.timeout.connect(self._ai_stream_tick)
        self._ai_stream_timer.start()
        self.ai_gen = threading.Thread(target=task, daemon=True)
        self.ai_gen.start()

    def _ai_stream_tick(self):
        """轮询流式增量队列 -> 更新最后一条 AI 气泡的文本（打字机效果）。

        流式期间若用户切换了联系人：增量不写进当前模型（避免串会话），
        结束时把完整问答追加回「发起请求时」那个联系人会话。
        """
        got = []
        done = False
        try:
            while True:
                item = self._ai_delta_q.get_nowait()
                if item == "__DONE__":
                    done = True
                    break
                got.append(item)
        except Exception:
            pass
        same = self._cur_talker == getattr(self, "_ai_stream_talker", None)
        if got and same:
            txt = "".join(got)
            it = self.ai_chat_model.data(self.ai_chat_model.index(self.ai_chat_model.rowCount() - 1, 0),
                                         QtCore.Qt.ItemDataRole.UserRole) or {}
            it["text"] = (it.get("text") or "") + txt
            it["thinking"] = False
            self.ai_chat_model.touch_last()
        # 完成
        if self._ai_stream_timer.isActive() and not (self.ai_gen is not None and self.ai_gen.is_alive()):
            self._ai_stream_timer.stop()
            err = self._ai_done_holder.get("err") or ""
            if not same:
                # 已切换联系人：把这次问答完整追加回原会话（不污染当前界面）
                self._store_ai_offline(getattr(self, "_ai_stream_talker", None),
                                       getattr(self, "_ai_stream_q", ""),
                                       self._ai_done_holder.get("text", "") or "", err)
                self.btn_ai_send.setEnabled(True)
                self.btn_ai_analyze.setEnabled(True)
                self._ai_stream_talker = None
                return
            last_idx = self.ai_chat_model.rowCount() - 1
            it = self.ai_chat_model.data(self.ai_chat_model.index(last_idx, 0),
                                         QtCore.Qt.ItemDataRole.UserRole) or {}
            it["streaming"] = False
            it["thinking"] = False
            self._stop_thinking_anim()
            self.ai_chat_model.touch_last()
            if err:
                self._append_ai_chat("⚠ 错误", err)
            else:
                idx = self.ai_chat_model.rowCount() - 1
                it = self.ai_chat_model.data(self.ai_chat_model.index(idx, 0),
                                             QtCore.Qt.ItemDataRole.UserRole) or {}
                it["streaming"] = False
                if not it.get("text"):
                    it["text"] = self._ai_done_holder.get("text", "") or "（AI 返回为空）"
                self.ai_chat_model.touch_last()
            self.ai_status.setText("可以继续追问 AI（AI 会记住这段聊天的记录）")
            self.btn_ai_send.setEnabled(True)
            self.btn_ai_analyze.setEnabled(True)
            self._save_ai_conversation()
            self._ai_stream_talker = None

    def _store_ai_offline(self, talker: str, question: str, answer: str, err: str = ""):
        """把流式完成后发现已切换联系人的问答，写回原联系人会话（磁盘层）。"""
        if not talker or self.account is None:
            return
        extra = ""
        try:
            pop = ai_chats.load_conversation(self.account, talker)
            msgs = list(pop.get("messages") or [])
            extra = pop.get("extra_context") or ""
        except Exception:
            msgs = []
        if question:
            msgs.append({"who": "me", "text": question})
        if err:
            msgs.append({"who": "ai", "text": "⚠ 错误: " + err})
        elif answer:
            msgs.append({"who": "ai", "text": answer})
        try:
            ai_chats.save_conversation(self.account, talker, msgs, extra_context=extra)
        except Exception:
            pass

    def _append_ai_chat(self, who: str, text: str):
        """往对话区追加一条微信风格气泡（我右 / AI 左 / 系统居中）。"""
        if not text:
            return
        if who.startswith("👤"):
            kind = "me"
        elif who.startswith("🤖"):
            kind = "ai"
        else:
            kind = "sys"
        self.ai_chat_model.add({"who": kind, "text": text})
        self._save_ai_conversation()
        # 滚到底
        QtCore.QTimer.singleShot(0, lambda: self.ai_text.scrollToBottom())

    def _fill_thinking_bubble(self, text: str) -> bool:
        """把最后一条「思考中」气泡原地填成最终回答（不新增气泡）。成功返回 True。"""
        for i in range(self.ai_chat_model.rowCount() - 1, -1, -1):
            it = self.ai_chat_model.data(self.ai_chat_model.index(i, 0),
                                         QtCore.Qt.ItemDataRole.UserRole) or {}
            if it.get("thinking"):
                it["text"] = text
                it["thinking"] = False
                it["streaming"] = False
                self._stop_thinking_anim()
                self.ai_chat_model.touch_last()
                return True
        return False

    # ---- AI 思考中动画 ----
    def _start_thinking_anim(self):
        if getattr(self, "_ai_thinking_timer", None) is None:
            self._ai_thinking_n = 0
            self._ai_thinking_timer = QtCore.QTimer(self)
            self._ai_thinking_timer.setInterval(380)
            self._ai_thinking_timer.timeout.connect(self._thinking_tick)
        self._ai_thinking_n = 0
        self._ai_thinking_timer.start()

    def _stop_thinking_anim(self):
        t = getattr(self, "_ai_thinking_timer", None)
        if t is not None:
            t.stop()

    def _thinking_tick(self):
        self._ai_thinking_n = (self._ai_thinking_n + 1) % 3
        n = self._ai_thinking_n
        # 更新最后一条 thinking 气泡的圆点（model 里的对象是同一个，直接改字段后 touch）
        it = None
        for i in range(self.ai_chat_model.rowCount() - 1, -1, -1):
            cand = self.ai_chat_model.data(self.ai_chat_model.index(i, 0),
                                           QtCore.Qt.ItemDataRole.UserRole) or {}
            if cand.get("thinking"):
                it = cand
                break
        if it is None:
            self._stop_thinking_anim()
            return
        it["_dots"] = n
        # 让 view 只更新圆点动画，不重置 thinking 文本
        for b in reversed(self.ai_text._bubbles):
            if b["who"] == "ai" and b.get("browser") is not None:
                b["browser"].setMarkdown("**AI 正在思考** " + "●" * (n + 1))
                self.ai_text._fits(b)
                break
    @QtCore.Slot(str, str)
    def _ai_chat_done(self, text: str, err: str):
        self.ai_status.setText("")
        if err:
            self._append_ai_chat("⚠ 错误", err)
            return
        self._append_ai_chat("🤖 AI", text)
        # AI 回答可能含方案 → 提供复制
        self.ai_status.setText("可以继续问，或用右下角「复制」/「再出方案」")
        self.btn_ai_send.setEnabled(True)

    @QtCore.Slot(str, str)
    def _ai_done(self, text: str, err: str):
        first = self._ai_first_pending
        self._ai_first_pending = False
        if err:
            self.ai_chat_model.add({"who": "sys", "text": f"⚠ {err}"})
            self.ai_status.setText("")
            return
        self._stop_thinking_anim()
        if text:
            if self._fill_thinking_bubble(text):
                pass  # 原地填充占位气泡（分析完成）
            else:
                self.ai_chat_model.add({"who": "ai", "text": text})
            if first:
                self.ai_status.setText("✅ 分析完成：AI 已记住这段聊天的全量记录，可继续在下方追问")
            else:
                if self.ai.cfg.get("auto_copy"):
                    QtWidgets.QApplication.clipboard().setText(text)
                    self.ai_status.setText("✅ 已自动复制到剪贴板（直接到微信粘贴发送）；可点「再出方案」换一组")
                else:
                    self.ai_status.setText("选一个方案，点「📋 复制」粘贴到微信发送；可点「再出方案」换一组")
        else:
            self.ai_chat_model.add({"who": "sys", "text": "AI 返回为空，稍后再试"})
        self._save_ai_conversation()

    # ------------------------------------------------------------ 媒体密钥（图片/表情）

    def _extract_media_key(self):
        """提取微信媒体密钥：扫主进程内存 + 本地 V2 图片已知明文攻击。

        注意：微信 4.x 的图片密钥不落盘、不以字符串形态常驻内存，实测扫描
        命中率极低。图片显示请优先依赖「微信里打开过的图」——软件会自动读取
        微信的明文缓存，此按钮仅作兜底尝试。
        """
        if self._media_key_worker is not None and self._media_key_worker.is_alive():
            return
        self.btn_mediakey.setEnabled(False)
        self.btn_mediakey.setText("提取中…")
        self._status("扫描微信进程提取媒体密钥（约 30 秒）…")

        def task():
            try:
                from backend.core import media as media_mod
                from backend.core import memscan
                from Crypto.Cipher import AES
                # 扫描主进程
                pids = memscan.find_wechat_pids()
                parents = memscan._pid_parents()
                mains = [p for p in pids if parents.get(p) not in pids]
                result = memscan.ScanResult()
                for pid in mains:
                    memscan.scan_pid(pid, result, log=lambda m: None)
                # 本地 V2 图片样本（无需看图也尽可能找）
                acc = self.account or ""
                source = None
                for d in memscan.find_data_dirs():
                    if acc and os.path.isdir(os.path.join(d, acc)):
                        source = os.path.join(d, acc)
                        break
                blocks = media_mod.find_sample_blocks(source) if source else []
                key = media_mod.try_image_key(result.alnum, blocks) if blocks else None
                if not key and result.candidates:
                    # 再试 hex 候选
                    cands = set()
                    for s in result.candidates:
                        s2 = s.strip("x'").strip("'")
                        if len(s2) >= 64:
                            try:
                                cands.add(s2[:64][:32])
                                cands.add(s2[-64:][32:])
                            except Exception:
                                pass
                    key = media_mod.try_image_key(cands, blocks) if blocks else None
                if key:
                    os.makedirs(KEYS_DIR, exist_ok=True)
                    with open(os.path.join(KEYS_DIR, f"{acc}.image_key"), "w") as f:
                        f.write(key)
                    QtCore.QMetaObject.invokeMethod(self, "_media_key_done",
                                                    QtCore.Qt.ConnectionType.QueuedConnection,
                                                    QtCore.Q_ARG(str, ""), QtCore.Q_ARG(str, ""))
                else:
                    QtCore.QMetaObject.invokeMethod(self, "_media_key_done",
                                                    QtCore.Qt.ConnectionType.QueuedConnection,
                                                    QtCore.Q_ARG(str, ""),
                                                    QtCore.Q_ARG(str, "未找到媒体密钥。\n"
                                                    "        微信 4.x 的图片密钥无法从内存提取。\n"
                                                    "        图片请在微信里打开过一次，软件会自动读取缓存明文图。"))
            except Exception as e:
                QtCore.QMetaObject.invokeMethod(self, "_media_key_done",
                                                QtCore.Qt.ConnectionType.QueuedConnection,
                                                QtCore.Q_ARG(str, ""), QtCore.Q_ARG(str, str(e)))

        self._media_key_worker = threading.Thread(target=task, daemon=True)
        self._media_key_worker.start()

    @QtCore.Slot(str, str)
    def _media_key_done(self, _ok: str, err: str):
        self.btn_mediakey.setEnabled(True)
        self.btn_mediakey.setText("🎨 媒体密钥")
        if err:
            self._status(err)
            return
        self._status("✅ 媒体密钥已提取，图片/表情包可显示了！")
        # 刷新当前聊天让图片/表情显示
        if self._cur_talker:
            t = self._cur_talker
            self._msgs_cache.pop(t, None)
            self._show_chat(t)
        QtWidgets.QMessageBox.information(
            self, "媒体密钥", "✅ 已提取成功！\n图片和表情包现在可以显示了。\n（微信大版本更新后可能需要重新提取一次）")

    # ------------------------------------------------------------ 实时更新
    def _on_new_messages(self, talkers):
        QtCore.QMetaObject.invokeMethod(self, "_apply_new_messages",
                                        QtCore.Qt.ConnectionType.QueuedConnection)
    @QtCore.Slot()
    def _apply_new_messages(self):
        # 当前会话直接取业务状态，不能依赖联系人列表的 currentIndex：
        # 消息计数刷新会重排/重置列表模型，索引可能失效，导致当前聊天不刷新。
        cur_talker = self._cur_talker
        pre_len = len(self._cur_msgs) if cur_talker else -1
        self._refresh_contacts(incremental=True)
        if cur_talker is not None:
            # 当前聊天：静默更新——后台重读新数据后只更新 model，保留滚动位置
            self._msgs_cache.pop(cur_talker, None)
            self._msg_refresh_seq += 1
            request_id = self._msg_refresh_seq

            def load():
                try:
                    msgs = self.store.messages(cur_talker) if self.store else []
                except Exception:
                    msgs = []
                self._msgs_cache[cur_talker] = msgs
                QtCore.QMetaObject.invokeMethod(self, "_silent_update_chat",
                                                QtCore.Qt.ConnectionType.QueuedConnection,
                                                QtCore.Q_ARG(str, cur_talker),
                                                QtCore.Q_ARG(int, pre_len),
                                                QtCore.Q_ARG(int, request_id))

            threading.Thread(target=load, daemon=True).start()
        self._status("检测到新消息，已刷新 ✓")

    @QtCore.Slot(str, int, int)
    def _silent_update_chat(self, talker: str, pre_len: int, request_id: int):
        """静默增量刷新：更新当前聊天数据，但保留用户滚动位置（不跳底）。"""
        if request_id != self._msg_refresh_seq or talker != self._cur_talker:
            return  # 用户已切走
        display = self._cur_peer or talker
        msgs = self._msgs_cache.get(talker, [])
        self._render_msgs(talker, display, msgs, scroll=False)
        # AI：对方刚发了新消息且启用 → 自动出建议
        if (pre_len >= 0 and self.ai.enabled()
                and self.ai.cfg.get("trigger_on_peer", True)):
            if len(self._cur_msgs) > pre_len:
                last = self._cur_msgs[-1] if self._cur_msgs else None
                if last is not None and not last.get("is_self"):
                    self._gen_ai(force=False)

    def closeEvent(self, event):
        """关闭窗口前保存当前 AI 会话（消息 + 补充场景）。"""
        try:
            self._save_ai_conversation()
        except Exception:
            pass
        super().closeEvent(event)
def main():
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
if __name__ == "__main__":
    main()
