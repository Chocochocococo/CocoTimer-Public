"""新介面共用的小元件。"""
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QSizePolicy,
                               QToolButton, QVBoxLayout)

from cocotimer.ui.icons import icon


class FlowLayout(QLayout):
    """由左到右排列，放不下就換行（窄視窗時按鈕會自動折行）。"""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, apply):
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        gap = self.spacing()
        lines, line, x = [], [], area.x()
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if line and x + hint.width() > area.right() + 1:
                lines.append(line)
                line, x = [], area.x()
            line.append((item, hint, x))
            x += hint.width() + gap
        if line:
            lines.append(line)
        y = area.y()
        for line in lines:
            height = max(h.height() for _i, h, _x in line)
            if apply:
                for item, hint, left in line:  # 同一行的元件垂直置中（文字標籤和下拉選單對齊）
                    item.setGeometry(QRect(QPoint(left, y + (height - hint.height()) // 2), hint))
            y += height + gap
        return (y - gap if lines else y) - rect.y() + m.bottom()


def card(spacing=12, margins=(20, 18, 20, 18)) -> QFrame:
    frame = QFrame()
    frame.setProperty("card", True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return frame


def section(title: str, layout_cls=QVBoxLayout, spacing=10):
    """有標題的卡片（取代舊版的 QGroupBox 外框）。回傳（卡片, 放內容用的 layout）。"""
    frame = card(spacing=spacing)
    frame.layout().addWidget(label(title, role="h2"))
    inner = layout_cls()
    inner.setContentsMargins(0, 0, 0, 0)
    frame.layout().addLayout(inner)
    return frame, inner


def label(text="", role=None, muted=False, chip=None, wrap=False) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    if muted:
        lab.setProperty("muted", True)
    if chip:
        lab.setProperty("chip", chip)
        lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    if wrap:
        lab.setWordWrap(True)
    return lab


def set_tone(lab: QLabel, tone: str = ""):
    """文字語氣色：danger（逾期）、warn（快到期）、success；空字串表示一般文字。顏色會跟著淺色／深色主題。"""
    if (lab.property("tone") or "") != tone:
        lab.setProperty("tone", tone)
        lab.style().unpolish(lab)
        lab.style().polish(lab)


def set_chip(lab: QLabel, kind: str, text: str):
    lab.setText(text)
    if lab.property("chip") != kind:
        lab.setProperty("chip", kind)
        lab.style().unpolish(lab)
        lab.style().polish(lab)


def button(text="", primary=False, link=False, pill=False, danger=False, checkable=False) -> QPushButton:
    btn = QPushButton(text)
    for name, on in (("primary", primary), ("link", link), ("pill", pill), ("danger", danger)):
        if on:
            btn.setProperty(name, True)
    btn.setCheckable(checkable)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def icon_button(name, color, tooltip, size=20) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName("iconButton")
    btn.setIcon(icon(name, color, size))
    btn.setIconSize(QSize(size, size))
    btn.setToolTip(tooltip)
    btn.setAccessibleName(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


class SegmentBar(QFrame):
    """分段按鈕（一次只能選一個），例如任務列表的「進行中／待收款／已結案／全部」。"""
    changed = Signal(str)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setProperty("segmentBar", True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.group = QButtonGroup(self)
        self.buttons = {}
        self.labels = dict(items)
        for key, text in items:
            btn = QPushButton(text)
            btn.setProperty("segment", True)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self.changed.emit(k))
            self.group.addButton(btn)
            self.buttons[key] = btn
            layout.addWidget(btn)

    def set_compact(self, compact: bool):
        """窄的時候縮小按鈕左右留白，並平均分配寬度。"""
        if self.property("compact") == compact:
            return
        self.setProperty("compact", compact)
        for btn in self.buttons.values():
            btn.setProperty("compact", compact)
            btn.setSizePolicy(QSizePolicy.Expanding if compact else QSizePolicy.Preferred, QSizePolicy.Fixed)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_current(self, key):
        if key in self.buttons:
            self.buttons[key].setChecked(True)

    def set_counts(self, counts):
        for key, btn in self.buttons.items():
            btn.setText(f"{self.labels[key]}  {counts.get(key, 0)}" if key in counts else self.labels[key])
