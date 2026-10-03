"""簡單的長條圖（自己畫，不需要額外的圖表套件）。

單一數列：同一個顏色；選取中的那一根用強調色，其他用淡一點的同色系。
細長條（最寬 24px）、頂端 4px 圓角、淡淡的水平格線；滑鼠移上去顯示數值。
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from cocotimer import theme as theme_module


def nice_step(raw: float) -> float:
    if raw <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * exp >= raw:
            return m * exp
    return 10 * exp


def compact_number(value: float) -> str:
    """12000 → 1.2萬、950 → 950。"""
    if abs(value) >= 10000:
        text = f"{value / 10000:.1f}".rstrip("0").rstrip(".")
        return f"{text}萬"
    return f"{value:,.0f}" if value == int(value) else f"{value:,.1f}"


class BarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.values = []
        self.labels = []
        self.highlight = None
        self.axis_format = compact_number
        self.value_format = compact_number
        self.tooltip_format = None
        self.label_every = None
        self.empty_text = "這段期間沒有資料"
        self.colors = {}
        self._hover = None

    def set_colors(self, colors):
        self.colors = colors
        self.update()

    def set_data(self, values, labels, highlight=None, axis_format=None, value_format=None, tooltip_format=None,
                 label_every=None):
        self.values = [max(0.0, float(v)) for v in values]
        self.labels = labels
        self.highlight = highlight
        self.axis_format = axis_format or compact_number
        self.value_format = value_format or self.axis_format
        self.tooltip_format = tooltip_format
        self.label_every = label_every  # None：依標籤寬度自動決定隔幾根標一次
        self.update()

    # --- 版面 ---

    def _layout(self):
        font = QFont(self.font())
        font.setPixelSize(11)
        fm = QFontMetrics(font)
        peak = max(self.values) if self.values else 0
        step = nice_step(peak / 4) if peak else 1
        top = step * max(1, math.ceil(peak / step))
        ticks = [step * i for i in range(int(round(top / step)) + 1)]
        left = max(fm.horizontalAdvance(self.axis_format(t)) for t in ticks) + 10
        plot = QRectF(left, 22, max(10, self.width() - left - 6), max(10, self.height() - 22 - fm.height() - 10))
        return font, fm, plot, top, ticks

    def _slot(self, plot, index):
        n = max(1, len(self.values))
        w = plot.width() / n
        return QRectF(plot.left() + index * w, plot.top(), w, plot.height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.colors
        ink, muted = QColor(c.get("ink", "#33261D")), QColor(c.get("muted", "#6E5B4E"))
        line = QColor(c.get("line", "#E6DCD0"))
        accent = QColor(c.get("accent", "#A3521F"))
        soft = QColor(theme_module.mix(c.get("accent", "#A3521F"), c.get("surface", "#FFFFFF"), 0.55))
        font, fm, plot, top, ticks = self._layout()
        p.setFont(font)

        if not self.values or not any(self.values):
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignCenter, self.empty_text)
            return

        # 格線與刻度
        for t in ticks:
            y = plot.bottom() - plot.height() * (t / top)
            p.setPen(QPen(line, 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(muted)
            p.drawText(QRectF(0, y - fm.height() / 2, plot.left() - 8, fm.height()), Qt.AlignRight | Qt.AlignVCenter,
                       self.axis_format(t))

        every = self.label_every
        if not every:  # 標籤之間至少留 6px，放不下就隔幾根標一次
            widest = max((fm.horizontalAdvance(t) for t in self.labels), default=0) + 6
            every = max(1, math.ceil(widest / max(1.0, plot.width() / len(self.values))))
        # 長條
        for i, v in enumerate(self.values):
            slot = self._slot(plot, i)
            bar_w = min(24.0, max(3.0, slot.width() * 0.62))
            h = plot.height() * (v / top)
            x = slot.center().x() - bar_w / 2
            emphasized = self.highlight is None or i == self.highlight or i == self._hover
            if h > 0:
                r = min(4.0, bar_w / 2, h)
                top_y, base = plot.bottom() - h, plot.bottom()
                path = QPainterPath()  # 頂端圓角、底部直角
                path.moveTo(x, base)
                path.lineTo(x, top_y + r)
                path.quadTo(x, top_y, x + r, top_y)
                path.lineTo(x + bar_w - r, top_y)
                path.quadTo(x + bar_w, top_y, x + bar_w, top_y + r)
                path.lineTo(x + bar_w, base)
                path.closeSubpath()
                p.fillPath(path, accent if emphasized else soft)
            # X 軸標籤
            near_highlight = self.highlight is not None and i != self.highlight and abs(i - self.highlight) < every
            if (i % every == 0 and not near_highlight) or i == self.highlight:
                p.setPen(ink if i == self.highlight else muted)
                p.drawText(QRectF(slot.left() - 10, plot.bottom() + 6, slot.width() + 20, fm.height()),
                           Qt.AlignHCenter | Qt.AlignTop, self.labels[i] if i < len(self.labels) else "")
        # 只在選取中的那一根標數值（其他的看格線或滑鼠提示）
        if self.highlight is not None and 0 <= self.highlight < len(self.values) and self.values[self.highlight] > 0:
            slot = self._slot(plot, self.highlight)
            y = plot.bottom() - plot.height() * (self.values[self.highlight] / top)
            p.setPen(ink)
            bold = QFont(font)
            bold.setBold(True)
            p.setFont(bold)
            text = self.value_format(self.values[self.highlight])
            w = QFontMetrics(bold).horizontalAdvance(text) + 8
            p.drawText(QRectF(slot.center().x() - w / 2, y - fm.height() - 4, w, fm.height()), Qt.AlignCenter, text)

    # --- 滑鼠 ---

    def mouseMoveEvent(self, event):
        if not self.values:
            return
        _font, _fm, plot, _top, _ticks = self._layout()
        x = event.position().x()
        index = int((x - plot.left()) // (plot.width() / len(self.values))) if plot.left() <= x <= plot.right() else None
        if index != self._hover:
            self._hover = index
            self.update()
        if index is not None and 0 <= index < len(self.values):
            text = self.tooltip_format(index) if self.tooltip_format else \
                f"{self.labels[index]}：{self.value_format(self.values[index])}"
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event):
        self._hover = None
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)
