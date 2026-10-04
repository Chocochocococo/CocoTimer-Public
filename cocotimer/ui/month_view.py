"""月曆格子（自己畫，不用一格一格建元件，比較省資源）。

- 完整模式（行事曆頁）：日期、農曆或假日名稱、最多三個彩色標籤
- 精簡模式（懸浮日曆）：日期、農曆或假日名稱、小圓點；滑鼠移上去顯示當天詳情
"""
from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from cocotimer import agenda
from cocotimer.lunar import lunar_text

WEEK_HEAD = "日一二三四五六"
LIGHT_KINDS = {"event": ("#1F4F8A", "#E4EDF8", "#2F6DB5"), "due": ("#7A4B00", "#FBEFD5", "#C98A1B"),
               "overdue": ("#9E2219", "#FBE3E0", "#B3261E"), "done": ("#6E5B4E", "#F1EAE1", "#B8A796")}
DARK_KINDS = {"event": ("#CFE0F5", "#2B3A4D", "#6FA8E8"), "due": ("#F5DDA8", "#4A3A1C", "#E8B04A"),
              "overdue": ("#F7C4BE", "#4D2420", "#F08A7E"), "done": ("#B8A796", "#3A302A", "#8A7A6C")}


def short_lunar(d: date) -> str:
    text = lunar_text(d)
    if not text:
        return ""
    return text[:-2] if text.endswith("初一") else text[-2:]


class MonthView(QWidget):
    selected = Signal(object)  # date
    activated = Signal(object)  # 雙擊某一天

    def __init__(self, compact=False, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.set_compact(compact)
        self.year = self.month = None
        self.days = []
        self.items = {}
        self.holidays = {}
        self.off = set()
        self.lunar = {}
        self.selected_day = None
        self.today = date.today()
        self.colors = {}
        self.dark = False
        self._hover = None

    def set_compact(self, compact):
        """精簡模式（圓點）或完整模式（標籤）；行事曆頁在窄視窗時會切到精簡模式。"""
        self.compact = compact
        self.setMinimumSize(240 if compact else 480, 240 if compact else 420)
        self.update()

    # --- 資料 ---

    def set_colors(self, colors, dark=False):
        self.colors = colors
        self.dark = dark
        self.update()

    def set_month(self, year, month):
        if (year, month) != (self.year, self.month):
            self.year, self.month = year, month
            self.days = agenda.month_days(year, month)
            self.lunar = {d: short_lunar(d) for d in self.days}
        self.today = date.today()
        self.update()

    def set_data(self, items, holiday_names, off_days):
        self.items, self.holidays, self.off = items, holiday_names, off_days
        self.update()

    def set_selected(self, day):
        self.selected_day = day
        self.update()

    # --- 版面 ---

    def _metrics(self):
        head = 22 if self.compact else 30
        rows = max(1, len(self.days) // 7)
        cell_w = self.width() / 7
        cell_h = (self.height() - head) / rows
        return head, cell_w, cell_h

    def _day_at(self, pos):
        head, cw, ch = self._metrics()
        if pos.y() < head:
            return None
        col, row = int(pos.x() // cw), int((pos.y() - head) // ch)
        index = row * 7 + col
        return self.days[index] if 0 <= col < 7 and 0 <= index < len(self.days) else None

    def _palette(self):
        c = self.colors
        return {
            "ink": QColor(c.get("ink", "#33261D")), "muted": QColor(c.get("muted", "#6E5B4E")),
            "line": QColor(c.get("line", "#E6DCD0")), "accent": QColor(c.get("accent", "#A3521F")),
            "accent_text": QColor(c.get("accent_text", "#FFFFFF")), "weekend": QColor(c.get("weekend", "#B3261E")),
            "other": QColor(c.get("other_month", "#B3A496")), "soft": QColor(c.get("accent_soft", "#F6E7DA")),
            "surface": QColor(c.get("surface", "#FFFFFF")), "ground": QColor(c.get("ground", "#F8F4EE")),
            "highlight": QColor(c.get("highlight", c.get("accent_soft", "#F6E7DA"))),
        }

    def paintEvent(self, event):
        if not self.days:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self._palette()
        kinds = DARK_KINDS if self.dark else LIGHT_KINDS
        head, cw, ch = self._metrics()
        base = QFont(self.font())

        head_font = QFont(base)
        head_font.setPixelSize(11 if self.compact else 12)
        head_font.setBold(True)
        p.setFont(head_font)
        for i, text in enumerate(WEEK_HEAD):
            p.setPen(pal["weekend"] if i in (0, 6) else pal["muted"])
            rect = QRectF(i * cw, 0, cw, head)
            p.drawText(rect.adjusted(0 if self.compact else 10, 0, 0, 0),
                       (Qt.AlignCenter if self.compact else Qt.AlignLeft | Qt.AlignVCenter), text)
        if not self.compact:
            p.setPen(pal["line"])
            p.drawLine(QPointF(0, head - 0.5), QPointF(self.width(), head - 0.5))

        for index, day in enumerate(self.days):
            row, col = divmod(index, 7)
            cell = QRectF(col * cw, head + row * ch, cw, ch)
            self._paint_cell(p, cell, day, pal, kinds, base)
        p.end()

    def _paint_cell(self, p, cell, day, pal, kinds, base):
        key = day.isoformat()
        in_month = day.month == self.month
        is_today = day == self.today
        selected = day == self.selected_day
        holiday = self.holidays.get(key)
        off = key in self.off

        if not self.compact:
            if not in_month:
                p.fillRect(cell, pal["ground"])
            p.setPen(pal["line"])
            p.drawLine(cell.topRight(), cell.bottomRight())
            p.drawLine(cell.bottomLeft(), cell.bottomRight())
        if selected or (self._hover == day and self.compact):
            path = QPainterPath()
            path.addRoundedRect(cell.adjusted(2, 2, -2, -2), 9, 9)
            p.fillPath(path, pal["soft"])
            if selected and not self.compact:
                p.setPen(pal["accent"])
                p.drawPath(path)

        # 日期數字
        num_font = QFont(base)
        num_font.setPixelSize(max(12, min(16, int(cell.height() * 0.26))) if self.compact else 14)
        num_font.setBold(is_today)
        p.setFont(num_font)
        size = num_font.pixelSize() + 12
        if self.compact:
            num_rect = QRectF(cell.center().x() - size / 2, cell.top() + 4, size, size)
        else:
            num_rect = QRectF(cell.left() + 6, cell.top() + 6, size, size)
        busy = self.compact and in_month and any(i["kind"] != "done" for i in self.items.get(key, []))
        if is_today:
            p.setPen(Qt.NoPen)
            p.setBrush(pal["accent"])
            p.drawEllipse(num_rect)
            p.setPen(pal["accent_text"])
        elif busy:  # 小日曆只有點點不好認，有行程或任務的日子另外用強調色圈起來
            p.setPen(QPen(pal["accent"], 1.5))
            p.setBrush(pal["highlight"])
            p.drawEllipse(num_rect.adjusted(1, 1, -1, -1))
            p.setPen(pal["weekend"] if off else pal["ink"])
        else:
            color = pal["other"] if not in_month else (pal["weekend"] if off else pal["ink"])
            p.setPen(color)
        p.drawText(num_rect, Qt.AlignCenter, str(day.day))

        # 農曆或節日
        small = QFont(base)
        small.setPixelSize(10 if self.compact else 11)
        text = holiday["name"] if holiday and holiday.get("name") else self.lunar.get(day, "")
        if holiday and holiday.get("off") and in_month:
            small.setBold(True)
            p.setPen(pal["weekend"])
        else:
            p.setPen(pal["other"] if not in_month else pal["muted"])
        p.setFont(small)
        fm = QFontMetrics(small)
        if self.compact:
            sub_rect = QRectF(cell.left() + 2, num_rect.bottom() + 1, cell.width() - 4, fm.height())
            p.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignTop, fm.elidedText(text, Qt.ElideRight, int(sub_rect.width())))
        else:
            sub_rect = QRectF(num_rect.right() + 2, cell.top() + 6, cell.right() - num_rect.right() - 8, size)
            p.drawText(sub_rect, Qt.AlignRight | Qt.AlignVCenter, fm.elidedText(text, Qt.ElideRight, int(sub_rect.width())))

        items = self.items.get(key, [])
        if not items:
            return
        if self.compact:
            dots = items[:3]
            gap, r = 4, 2.6
            total = len(dots) * (r * 2) + (len(dots) - 1) * gap
            x = cell.center().x() - total / 2 + r
            y = min(cell.bottom() - 6, sub_rect.bottom() + 6)
            p.setPen(Qt.NoPen)
            for item in dots:
                p.setBrush(QColor(kinds[item["kind"]][2]))
                p.drawEllipse(QPointF(x, y), r, r)
                x += r * 2 + gap
            return
        chip_font = QFont(base)
        chip_font.setPixelSize(11)
        p.setFont(chip_font)
        cfm = QFontMetrics(chip_font)
        chip_h = cfm.height() + 4
        top = num_rect.bottom() + 4
        room = int((cell.bottom() - 6 - top) // (chip_h + 3))
        shown = items[:max(0, room if len(items) <= room else room - 1)]
        for item in shown:
            fg, bg, _dot = kinds[item["kind"]]
            rect = QRectF(cell.left() + 5, top, cell.width() - 10, chip_h)
            path = QPainterPath()
            path.addRoundedRect(rect, 5, 5)
            p.fillPath(path, QColor(bg))
            p.setPen(QColor(fg))
            label = (item["time"] + " " if item["time"] and len(shown) < 3 and rect.width() > 110 else "") + item["title"]
            chip_font.setStrikeOut(item["kind"] == "done")
            p.setFont(chip_font)
            p.drawText(rect.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                       cfm.elidedText(label, Qt.ElideRight, int(rect.width() - 10)))
            top += chip_h + 3
        chip_font.setStrikeOut(False)
        if len(items) > len(shown):
            p.setFont(chip_font)
            p.setPen(pal["muted"])
            p.drawText(QRectF(cell.left() + 8, top, cell.width() - 12, chip_h), Qt.AlignVCenter | Qt.AlignLeft,
                       f"還有 {len(items) - len(shown)} 項")

    # --- 滑鼠 ---

    def mousePressEvent(self, event):
        day = self._day_at(event.position())
        if day and event.button() == Qt.LeftButton:
            self.selected_day = day
            self.selected.emit(day)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        day = self._day_at(event.position())
        if day:
            self.activated.emit(day)

    def mouseMoveEvent(self, event):
        day = self._day_at(event.position())
        if day != self._hover:
            self._hover = day
            self.update()
            if self.compact:
                self._show_tooltip(day, event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover = None
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def _show_tooltip(self, day, pos):
        if day is None:
            QToolTip.hideText()
            return
        key = day.isoformat()
        lines = [f"<b>{day.month} 月 {day.day} 日（{WEEK_HEAD[(day.weekday() + 1) % 7]}）</b>"
                 + (f" · {lunar_text(day)}" if lunar_text(day) else "")]
        if key in self.holidays:
            lines.append(f"🎌 {self.holidays[key]['name']}")
        for item in self.items.get(key, []):
            style = "text-decoration: line-through; color: #888;" if item["kind"] == "done" else ""
            detail = f"<br><span style='color:#888'>{item['detail']}</span>" if item.get("detail") else ""
            lines.append(f"<span style='{style}'>{item['time']} {item['title']}</span>{detail}")
        if len(lines) == 1:
            lines.append("<span style='color:#888'>沒有安排</span>")
        QToolTip.showText(pos, "<br>".join(lines), self)
