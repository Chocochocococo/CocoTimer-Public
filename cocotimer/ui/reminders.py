"""提醒視窗：行程到了、任務快到期或到期時跳出來的卡片（顏色跟著目前的配色，淺色深色都適用）。"""
from datetime import datetime

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QToolButton, QVBoxLayout, QWidget

from cocotimer import tasks as tasks_service
from cocotimer import theme as theme_module
from cocotimer.models import Event, TaskItem
from cocotimer.ui.icons import icon
from cocotimer.ui.month_view import DARK_KINDS, LIGHT_KINDS
from cocotimer.ui.widgets import button, label

WEEKDAYS = "一二三四五六日"
_open_count = 0  # 同時有好幾個提醒時，一個一個往下錯開，不要疊在一起


def _when(date_text: str, time_text: str) -> str:
    try:
        d = datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return f"{date_text} {time_text}"
    return f"{d.month} 月 {d.day} 日（{WEEKDAYS[d.weekday()]}）{time_text}"


class ReminderCard(QWidget):
    """提醒卡片的共用外框：圓角卡片、左側色條、標題列、可以拖曳、右上角關閉。"""
    WIDTH = 420

    def __init__(self, kind_label, stripe, colors, parent=None):
        super().__init__(parent)
        self.colors = colors
        self.stripe = QColor(stripe)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedWidth(self.WIDTH)
        self._drag = None
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(30, 20, 22, 20)
        self.body.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.kind = label(kind_label)
        self.kind.setStyleSheet(f"color: {stripe}; font-weight: 700; background: transparent;")
        head.addWidget(self.kind)
        head.addStretch()
        self.clock = label(datetime.now().strftime("%H:%M"), muted=True)
        head.addWidget(self.clock)
        close = QToolButton()
        close.setIcon(icon("close", colors["muted"], 16))
        close.setAutoRaise(True)
        close.setToolTip("關閉")
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet("QToolButton { border: none; background: transparent; padding: 2px; }")
        close.clicked.connect(self.dismiss)
        head.addWidget(close)
        self.body.addLayout(head)

    def title(self, text):
        lab = label(text, wrap=True)
        lab.setStyleSheet("font-size: 18px; font-weight: 700; background: transparent;")
        self.body.addWidget(lab)
        return lab

    def line(self, text, muted=True):
        lab = label(text, muted=muted, wrap=True)
        lab.setStyleSheet("background: transparent;")
        self.body.addWidget(lab)
        return lab

    def description(self, text):
        text = (text or "").strip()
        if not text:
            return
        if len(text) > 160:
            text = text[:160] + "…"
        lab = label(text, muted=True, wrap=True)
        lab.setStyleSheet(f"background: {theme_module.mix(self.colors['ground'], self.colors['surface'], 0.5)};"
                          " border-radius: 8px; padding: 8px 10px;")
        self.body.addWidget(lab)

    def place(self):
        """放在螢幕中間；同時有好幾個時往下錯開。"""
        global _open_count
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        offset = (_open_count % 5) * 28
        _open_count += 1
        self.move(screen.center() - self.rect().center() + QPoint(offset, offset))

    def dismiss(self):
        global _open_count
        _open_count = max(0, _open_count - 1)
        self.close()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        p.fillPath(path, QColor(self.colors["surface"]))
        p.setPen(QPen(QColor(self.colors["line_strong"]), 1))
        p.drawPath(path)
        p.setClipPath(path)
        p.fillRect(QRectF(rect.left(), rect.top(), 6, rect.height()), self.stripe)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        self._drag = None


def _colors(parent):
    colors = getattr(parent, "colors", None)
    if colors:
        return colors
    from cocotimer.models import ThemeConfig
    return theme_module.tokens(ThemeConfig())


def _kinds(colors):
    return DARK_KINDS if theme_module.is_dark(colors) else LIGHT_KINDS


class EventReminderWindow(ReminderCard):
    completed_signal = Signal(str)

    def __init__(self, event: Event, parent=None):
        colors = _colors(parent)
        super().__init__("行程提醒", _kinds(colors)["event"][2], colors, parent)
        self.event_data = event
        self.main_window = parent
        self.title(event.title)
        self.line(_when(event.date, event.time))
        self.description(event.description)
        self.body.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        if parent is not None and hasattr(parent, "show_day"):
            open_btn = button("在行事曆中查看", link=True)
            open_btn.clicked.connect(self._open)
            row.addWidget(open_btn)
        row.addStretch()
        done = button("標記為已完成")
        done.clicked.connect(self._complete)
        self.ok_btn = button("知道了", primary=True)
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.dismiss)
        row.addWidget(done)
        row.addWidget(self.ok_btn)
        self.body.addLayout(row)
        self.place()

    def _complete(self):
        self.completed_signal.emit(self.event_data.id)
        self.dismiss()

    def _open(self):
        from datetime import date
        try:
            self.main_window.show_day(date.fromisoformat(self.event_data.date))
        except ValueError:
            pass
        self.dismiss()


class TaskReminderWindow(ReminderCard):
    """任務提醒。is_due=True 是到期提醒，False 是提前提醒。可以直接調整完成度。"""
    completion_changed = Signal(str, int)

    def __init__(self, task: TaskItem, is_due=False, parent=None):
        colors = _colors(parent)
        stripe = colors["danger"] if is_due else colors["warn"]
        super().__init__("任務到期了" if is_due else "任務快到期", stripe, colors, parent)
        self.task_data = task
        self.is_due = is_due
        self.main_window = parent
        self.title(task.title)
        meta = " · ".join(p for p in (task.project_name, task.client) if p)
        if meta:
            self.line(meta)
        note, _kind = tasks_service.due_info(task)
        self.line(f"交件時間：{_when(task.due_date, task.due_time)}（{note}）", muted=False)
        self.description(task.description)

        self.body.addSpacing(4)
        progress = QHBoxLayout()
        progress.setSpacing(10)
        progress.addWidget(label("完成度", muted=True))
        self.completion_slider = QSlider(Qt.Horizontal)
        self.completion_slider.setRange(0, 100)
        self.completion_slider.setSingleStep(5)
        self.completion_slider.setPageStep(10)
        self.completion_slider.setValue(task.completion)
        self.completion_value_label = label(f"{task.completion}%", role="mono")
        self.completion_value_label.setMinimumWidth(44)
        self.completion_value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.completion_slider.valueChanged.connect(lambda v: self.completion_value_label.setText(f"{v}%"))
        progress.addWidget(self.completion_slider, 1)
        progress.addWidget(self.completion_value_label)
        self.body.addLayout(progress)

        row = QHBoxLayout()
        row.setSpacing(8)
        if parent is not None and hasattr(parent, "open_task"):
            open_btn = button("開啟任務", link=True)
            open_btn.clicked.connect(self._open)
            row.addWidget(open_btn)
        row.addStretch()
        self.ok_btn = button("知道了", primary=True)
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self._on_ok_clicked)
        row.addWidget(self.ok_btn)
        self.body.addSpacing(6)
        self.body.addLayout(row)
        self.place()

    def _save_completion(self):
        value = self.completion_slider.value()
        if value != self.task_data.completion:
            self.completion_changed.emit(self.task_data.id, value)

    def _on_ok_clicked(self):
        self._save_completion()
        self.dismiss()

    def _open(self):
        self._save_completion()
        self.dismiss()
        self.main_window.restore_from_tray()
        self.main_window.open_task(self.task_data.id)


class ToastNotification(QWidget):
    """短暫的通知（番茄鐘、喝水），幾秒後自己淡出，不會搶走焦點。"""

    def __init__(self, title, message, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QPropertyAnimation, QTimer
        self.colors = _colors(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(f"color: {self.colors['ink']}; font-size: 16px; font-weight: 700; background: transparent;")
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(f"color: {self.colors['muted']}; background: transparent;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)
        self.setFixedWidth(420)
        self.adjustSize()
        self.animation = QPropertyAnimation(self, b"windowOpacity", self)
        QTimer.singleShot(5000, self.fade_out)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 14, 14)
        p.fillPath(path, QColor(self.colors["surface"]))
        p.setPen(QPen(QColor(self.colors["line_strong"]), 1))
        p.drawPath(path)
        p.setClipPath(path)
        p.fillRect(QRectF(1, 1, 5, self.height() - 2), QColor(self.colors["accent"]))

    def showEvent(self, event):
        self.animation.setDuration(300)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
        super().showEvent(event)

    def fade_out(self):
        self.animation.setDuration(500)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.close)
        self.animation.start()
