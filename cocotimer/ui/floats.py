"""懸浮小工具：時鐘、日曆、週曆橫條、番茄鐘、工時計時、合併迷你條。

共用的基底 FloatWindow 負責：半透明圓角外框（淺色／深色）、拖曳移動、右下角縮放、
右鍵選單（鎖定位置、深色外觀、隱藏），位置由 DataManager 自動記錄。
"""
from datetime import date, datetime, timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QProgressBar, QStackedWidget, QToolButton, QToolTip,
                               QVBoxLayout, QWidget)

from cocotimer import agenda
from cocotimer import tasks as tasks_service
from cocotimer import theme as theme_module
from cocotimer.lunar import lunar_text
from cocotimer.ui.icons import icon
from cocotimer.ui.month_view import DARK_KINDS, LIGHT_KINDS, MonthView, short_lunar

WEEKDAYS = "一二三四五六日"
MONO = ["DM Mono", "Cascadia Mono", "Consolas", "Courier New", "monospace"]


OPACITY_CHOICES = (100, 90, 80, 70, 60, 50, 40)


def float_palette(tokens, dark, opacity=100):
    """opacity：背景不透明度（%）。只影響底色，文字與圖示維持清楚。"""
    alpha = round(255 * max(15, min(100, opacity)) / 100)
    if dark:
        accent = theme_module.mix(tokens["accent"], "#FFFFFF", 0.35)
        return {"bg": QColor(36, 28, 23, alpha), "border": QColor(255, 255, 255, 22), "ink": QColor("#F5EDE4"),
                "muted": QColor("#C9B8A8"), "accent": QColor(accent), "track": QColor(255, 255, 255, 30),
                "ok": QColor("#5CC08A"), "accent_hex": accent, "ink_hex": "#F5EDE4", "muted_hex": "#C9B8A8",
                "weekend": QColor("#F08A7E"), "danger_hex": "#F08A7E", "warn_hex": "#E8B04A"}
    bg = QColor(theme_module.mix(tokens["surface"], tokens["ground"], 0.25))
    bg.setAlpha(alpha)
    return {"bg": bg, "border": QColor(51, 38, 29, 28),
            "ink": QColor(tokens["ink"]), "muted": QColor(tokens["muted"]), "accent": QColor(tokens["accent"]),
            "track": QColor(tokens["track"]), "ok": QColor(theme_module.SUCCESS), "accent_hex": tokens["accent"],
            "ink_hex": tokens["ink"], "muted_hex": tokens["muted"], "weekend": QColor(tokens["weekend"]),
            "danger_hex": "#B3261E", "warn_hex": "#C98A1B"}


def hms(seconds, hours=True):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if hours else f"{h * 60 + m:02d}:{s:02d}"


def mono_font(px, bold=False):
    font = QFont()
    font.setFamilies(MONO)
    font.setPixelSize(max(8, int(px)))
    font.setWeight(QFont.Medium if not bold else QFont.Bold)
    return font


class Dot(QWidget):
    """小圓點（狀態燈）。"""

    def __init__(self, size=8, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.color = QColor("#999")

    def set_color(self, color):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(self.rect())


class FloatWindow(QWidget):
    KEY = ""            # main window 的 FLOAT_SPECS 名稱
    GEOMETRY = ""       # 記錄位置用的名稱（沿用 v2 的名稱，升級後位置不會跑掉）
    DEFAULT_SIZE = (280, 120)
    MIN_SIZE = (160, 60)
    RADIUS = 18
    GRIP = 16

    def __init__(self, data_manager, controller=None):
        super().__init__(None)
        self.data_manager = data_manager
        self.controller = controller
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(*self.MIN_SIZE)
        self.resize(*self.DEFAULT_SIZE)
        self._drag = None
        self._resize = None
        self._hovered = False
        self.dark = False
        self.locked = False
        self.tokens = {}
        self.pal = {}
        self._built = False
        self.update_style(apply=False)
        self.build()
        self._built = True
        self.update_style()
        self.data_manager.restore_window_geometry(self.GEOMETRY, self)

    # 子類別實作
    def build(self):
        pass

    def restyle(self):
        pass

    def rescale(self):
        pass

    # --- 外觀 ---

    def update_style(self, apply=True):
        settings = self.data_manager.load_settings()
        self.dark = settings.floats_dark
        self.locked = settings.floats_locked
        self.tokens = theme_module.tokens(settings.theme)
        self.opacity = settings.floats_opacity
        self.settings = settings
        self.pal = float_palette(self.tokens, self.dark, self.opacity)
        self.font_family = settings.theme.font_family
        if apply:
            self.restyle()
            self.rescale()
            self.update()

    def label_style(self, muted=False, bold=False, color=None):
        c = color or (self.pal["muted_hex"] if muted else self.pal["ink_hex"])
        return (f"color: {c}; background: transparent; font-family: '{self.font_family}', 'Microsoft JhengHei';"
                + (" font-weight: 700;" if bold else ""))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = min(self.RADIUS, rect.height() / 2)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.fillPath(path, self.pal["bg"])
        p.setPen(QPen(self.pal["border"], 1))
        p.drawPath(path)
        if self._hovered and not self.locked:
            p.setPen(QPen(self.pal["muted"], 1.4))
            r = self.rect()
            for d in (5, 9):
                p.drawLine(QPointF(r.right() - 4, r.bottom() - d), QPointF(r.right() - d, r.bottom() - 4))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._built:
            self.rescale()

    # --- 拖曳、縮放、右鍵 ---

    def _in_grip(self, pos):
        return pos.x() > self.width() - self.GRIP and pos.y() > self.height() - self.GRIP

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self.locked:
            return super().mousePressEvent(event)
        pos = event.position().toPoint()
        if self._in_grip(pos):
            self._resize = (event.globalPosition().toPoint(), self.size())
        else:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            self.move(event.globalPosition().toPoint() - self._drag)
        elif self._resize is not None:
            start, size = self._resize
            delta = event.globalPosition().toPoint() - start
            self.resize(max(self.MIN_SIZE[0], size.width() + delta.x()), max(self.MIN_SIZE[1], size.height() + delta.y()))
        elif not self.locked:
            self.setCursor(Qt.SizeFDiagCursor if self._in_grip(event.position().toPoint()) else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = self._resize = None
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self.on_hover(True)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.on_hover(False)
        self.update()
        super().leaveEvent(event)

    def on_hover(self, hovered):
        pass

    def contextMenuEvent(self, event):
        if self.controller is None:
            return
        menu = QMenu(self)
        lock = menu.addAction("鎖定所有懸浮工具的位置")
        lock.setCheckable(True)
        lock.setChecked(self.locked)
        dark = menu.addAction("深色外觀")
        dark.setCheckable(True)
        dark.setChecked(self.dark)
        opacity_menu = menu.addMenu("背景不透明度")
        opacity_actions = {}
        for value in OPACITY_CHOICES:
            action = opacity_menu.addAction(f"{value}%" + ("（不透明）" if value == 100 else ""))
            action.setCheckable(True)
            action.setChecked(value == self.opacity)
            opacity_actions[action] = value
        extra = self.menu_items(menu)
        menu.addSeparator()
        hide = menu.addAction("隱藏")
        chosen = menu.exec(event.globalPos())
        if chosen in extra:
            extra[chosen]()
        if chosen is lock:
            self.controller.set_floats_option(floats_locked=lock.isChecked())
        elif chosen is dark:
            self.controller.set_floats_option(floats_dark=dark.isChecked())
        elif chosen in opacity_actions:
            self.controller.set_floats_option(floats_opacity=opacity_actions[chosen])
        elif chosen is hide:
            self.controller.set_float_visible(self.KEY, False)

    def menu_items(self, menu):
        """子類別可以在右鍵選單加上自己的選項，回傳 {action: 要執行的函式}。"""
        return {}

    def closeEvent(self, event):
        self.data_manager.save_window_geometry(self.GEOMETRY, self)
        super().closeEvent(event)

    def small_button(self, name, tooltip, slot):
        btn = QToolButton(self)
        btn.setIcon(icon(name, self.pal["ink_hex"], 16))
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        btn.setProperty("iconName", name)
        btn.clicked.connect(slot)
        return btn

    def recolor_buttons(self):
        for btn in self.findChildren(QToolButton):
            if btn.property("iconName"):
                btn.setIcon(icon(btn.property("iconName"), self.pal["ink_hex"], 16))
                btn.setStyleSheet("QToolButton { border: none; border-radius: 8px; padding: 4px; background: transparent; }"
                                  f"QToolButton:hover {{ background: {'rgba(255,255,255,0.12)' if self.dark else 'rgba(0,0,0,0.06)'}; }}")


# --- 數字時鐘 ---

class ClockFace(QWidget):
    """時鐘的內容：時間、日期、農曆三行，依視窗大小縮放，整塊垂直置中（不會因為視窗拉高就分得很開）。"""
    GAPS = {"tight": 0.14, "normal": 0.26, "loose": 0.45}  # 時間與日期的間距（時間高度的比例）

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.time_text = self.date_text = self.lunar_text = ""

    def set_texts(self, time_text, date_text=None, lunar=None):
        self.time_text = time_text
        if date_text is not None:
            self.date_text, self.lunar_text = date_text, lunar or ""
        self.update()

    def fonts(self):
        w, h = max(1, self.width()), max(1, self.height())
        probe = mono_font(100)
        ratio = QFontMetricsF(probe).horizontalAdvance("00:00:00") / 100
        lines = 0.62 if self.lunar_text else 0.42  # 日期、農曆佔的高度（相對於時間字級）
        gap = self.GAPS.get(getattr(self.owner, "settings", None) and self.owner.settings.clock_gap, 0.26)
        px = min((w - 8) / ratio, h / (0.78 + gap * 0.78 + lines + 0.12))
        time_font = mono_font(px)
        date_font = QFont(self.owner.font_family)
        date_font.setPixelSize(max(11, int(px * 0.26)))
        date_font.setWeight(QFont.Medium)
        lunar_font = QFont(self.owner.font_family)
        lunar_font.setPixelSize(max(10, int(px * 0.21)))
        return time_font, date_font, lunar_font, gap

    def paintEvent(self, event):
        if not self.time_text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        time_font, date_font, lunar_font, gap = self.fonts()
        pal = self.owner.pal
        tm, dm, lm = QFontMetricsF(time_font), QFontMetricsF(date_font), QFontMetricsF(lunar_font)
        t_ink = tm.tightBoundingRect("00:00:00")   # 用固定字串量高度，秒數跳動時不會晃
        d_ink = dm.tightBoundingRect(self.date_text or "0")
        rows = [(time_font, self.time_text, t_ink, tm, pal["ink"]), (date_font, self.date_text, d_ink, dm, pal["muted"])]
        spaces = [t_ink.height() * gap]
        if self.lunar_text:
            rows.append((lunar_font, self.lunar_text, lm.tightBoundingRect(self.lunar_text), lm, pal["muted"]))
            spaces.append(dm.height() * 0.28)
        total = sum(r[2].height() for r in rows) + sum(spaces)
        y = (self.height() - total) / 2
        for i, (font, text, ink, fm, color) in enumerate(rows):
            p.setFont(font)
            p.setPen(color)
            x = (self.width() - fm.horizontalAdvance(text)) / 2
            p.drawText(QPointF(x, y - ink.top()), text)
            y += ink.height() + (spaces[i] if i < len(spaces) else 0)
        p.end()


class ClockFloat(FloatWindow):
    KEY, GEOMETRY = "clock", "digital_clock"
    DEFAULT_SIZE, MIN_SIZE = (420, 170), (200, 90)
    GAP_CHOICES = (("tight", "緊湊"), ("normal", "標準"), ("loose", "寬鬆"))

    def build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 12)
        self.face = ClockFace(self)
        layout.addWidget(self.face)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self._lunar_day = None
        self.tick()

    def restyle(self):
        self.face.update()

    def rescale(self):
        self.face.update()

    def tick(self):
        if not self.isVisible() and self.face.time_text:
            return
        now = datetime.now()
        if self._lunar_day != now.date():
            self._lunar_day = now.date()
            self.face.set_texts(now.strftime("%H:%M:%S"),
                                f"{now.year} 年 {now.month} 月 {now.day} 日（{WEEKDAYS[now.weekday()]}）",
                                lunar_text(now.date()))
        else:
            self.face.set_texts(now.strftime("%H:%M:%S"))

    def menu_items(self, menu):
        sub_menu = menu.addMenu("時間與日期的間距")
        current = self.settings.clock_gap
        actions = {}
        for key, text in self.GAP_CHOICES:
            action = sub_menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(key == current)
            actions[action] = lambda k=key: self.set_gap(k)
        return actions

    def set_gap(self, key):
        if self.controller is not None:
            self.controller.update_settings(clock_gap=key)
        self.update_style()


# --- 番茄鐘 ---

class PomodoroFloat(FloatWindow):
    KEY, GEOMETRY = "pomodoro", "pomodoro_float"
    DEFAULT_SIZE, MIN_SIZE = (280, 132), (200, 100)
    PHASES = {"idle": "未開始", "working": "專注中", "breaking": "休息中", "paused": "已暫停"}

    def build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.dot = Dot()
        self.phase = QLabel("未開始")
        top.addWidget(self.dot)
        top.addWidget(self.phase, 1)
        layout.addLayout(top)
        self.time_label = QLabel("25:00")
        layout.addWidget(self.time_label, 1)
        self.bottom = QStackedWidget()
        self.bottom.setStyleSheet("background: transparent;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        bar_holder = QWidget()
        bh = QVBoxLayout(bar_holder)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.addStretch()
        bh.addWidget(self.bar)
        controls = QWidget()
        ch = QHBoxLayout(controls)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(4)
        self.main_btn = self.small_button("play", "開始／暫停", lambda: self.controller and self.controller.pomodoro_primary_action())
        self.skip_btn = self.small_button("skip", "略過這一輪", lambda: self.controller and self.controller.pomodoro_skip())
        self.reset_btn = self.small_button("reset", "停止並重設", lambda: self.controller and self.controller.pomodoro_reset())
        for b in (self.main_btn, self.skip_btn, self.reset_btn):
            ch.addWidget(b)
        ch.addStretch()
        self.bottom.addWidget(bar_holder)
        self.bottom.addWidget(controls)
        self.bottom.setFixedHeight(30)
        layout.addWidget(self.bottom)
        self.status = {"state": "idle", "remaining": 1500, "total": 1500}

    def restyle(self):
        self.phase.setStyleSheet(self.label_style(bold=True, color=self.pal["accent_hex"]))
        self.time_label.setStyleSheet(self.label_style())
        self.bar.setStyleSheet(f"QProgressBar {{ background: {self.pal['track'].name(QColor.HexArgb)}; border: none; border-radius: 2px; }}"
                               f"QProgressBar::chunk {{ background: {self.pal['accent_hex']}; border-radius: 2px; }}")
        self.recolor_buttons()
        self.update_status(self.status)

    def rescale(self):
        h = self.height()
        self.time_label.setFont(mono_font(h * 0.34))
        f = QFont(self.font_family)
        f.setPixelSize(max(11, int(h * 0.095)))
        f.setBold(True)
        self.phase.setFont(f)

    def on_hover(self, hovered):
        self.bottom.setCurrentIndex(1 if hovered and self.controller else 0)

    def update_status(self, status):
        self.status = status
        state = status["state"]
        phase = self.PHASES.get(state, "")
        task = status.get("task") or ""
        text = f"{phase} · {task}" if task else phase
        width = max(40, self.phase.width())
        self.phase.setText(self.phase.fontMetrics().elidedText(text, Qt.ElideRight, width))
        self.phase.setToolTip(text if task else "")
        self.dot.set_color(self.pal["ok"] if state == "breaking" else (self.pal["muted"] if state in ("idle", "paused") else self.pal["accent"]))
        self.time_label.setText(hms(status["remaining"], hours=False))
        total = status["total"] or 1
        self.bar.setValue(int(1000 * (1 - status["remaining"] / total)) if state != "idle" else 0)
        name = "pause" if state in ("working", "breaking") else "play"
        self.main_btn.setProperty("iconName", name)
        self.main_btn.setIcon(icon(name, self.pal["ink_hex"], 16))


# --- 工時計時 ---

class WorkFloat(FloatWindow):
    KEY, GEOMETRY = "work", "work_time_float"
    DEFAULT_SIZE, MIN_SIZE = (250, 120), (180, 90)

    def build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.dot = Dot()
        self.state = QLabel("未打卡")
        top.addWidget(self.dot)
        top.addWidget(self.state, 1)
        layout.addLayout(top)
        self.time_label = QLabel("00:00:00")
        layout.addWidget(self.time_label, 1)
        self.note = QLabel("")
        layout.addWidget(self.note)
        self.status = {"working": False, "current": 0, "total": 0, "sessions": 0}

    def restyle(self):
        self.time_label.setStyleSheet(self.label_style())
        self.note.setStyleSheet(self.label_style(muted=True))
        self.update_status(self.status)

    def rescale(self):
        h = self.height()
        self.time_label.setFont(mono_font(h * 0.30))
        for lab, scale, bold in ((self.state, 0.10, True), (self.note, 0.095, False)):
            f = QFont(self.font_family)
            f.setPixelSize(max(11, int(h * scale)))
            f.setBold(bold)
            lab.setFont(f)

    def update_status(self, status):
        self.status = status
        working = status["working"]
        color = self.pal["ok"] if working else self.pal["muted"]
        self.dot.set_color(color)
        self.state.setText("工作中" if working else ("休息中" if status["sessions"] else "未打卡"))
        self.state.setStyleSheet(self.label_style(bold=True, color=color.name()))
        self.time_label.setText(hms(status["current"] if working else status["total"]))
        total = status["total"]
        self.note.setText(f"今日累計 {int(total // 3600)} 小時 {int(total % 3600 // 60):02d} 分" if working else
                          (f"今日共 {status['sessions']} 段" if status["sessions"] else "今天還沒打卡"))


# --- 日曆 ---

class CalendarFloat(FloatWindow):
    KEY, GEOMETRY = "calendar", "calendar_window"
    DEFAULT_SIZE, MIN_SIZE = (420, 400), (280, 260)

    def build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 14)
        layout.setSpacing(6)
        head = QHBoxLayout()
        self.title = QLabel()
        head.addWidget(self.title, 1)
        self.prev_btn = self.small_button("chevron_left", "上個月", lambda: self.shift(-1))
        self.today_btn = self.small_button("today", "回到這個月", self.go_today)
        self.next_btn = self.small_button("chevron_right", "下個月", lambda: self.shift(1))
        for b in (self.prev_btn, self.today_btn, self.next_btn):
            head.addWidget(b)
        layout.addLayout(head)
        self.view = MonthView(compact=True)
        self.view.setMinimumSize(200, 160)
        self.view.activated.connect(self._open_day)
        layout.addWidget(self.view, 1)
        today = date.today()
        self.year, self.month = today.year, today.month
        self.refresh_events()

    def restyle(self):
        f = QFont(self.font_family)
        f.setPixelSize(16)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet(self.label_style())
        self.view.setFont(QFont(self.font_family))
        colors = dict(self.tokens)
        if self.dark:
            colors.update({"ink": "#F5EDE4", "muted": "#C9B8A8", "other_month": "#6E6158", "weekend": "#F08A7E",
                           "accent": self.pal["accent_hex"], "accent_text": "#241C17", "accent_soft": "#3A2D24",
                           "highlight": theme_module.mix(self.pal["accent_hex"], "#241C17", 0.78)})
        self.view.set_colors(colors, self.dark)
        self.recolor_buttons()

    def shift(self, months):
        index = self.year * 12 + self.month - 1 + months
        self.year, self.month = divmod(index, 12)
        self.month += 1
        self.refresh_events()

    def go_today(self):
        today = date.today()
        self.year, self.month = today.year, today.month
        self.refresh_events()

    def refresh_events(self):
        self.title.setText(f"{self.year} 年 {self.month} 月")
        self.view.set_month(self.year, self.month)
        events, tasks = self.data_manager.load_events(), self.data_manager.load_tasks()
        calendars = self.data_manager.load_holidays()
        ids = self.data_manager.load_billing().rule_for(None)["calendar_ids"]
        days = self.view.days
        self.view.set_data(agenda.month_items(self.year, self.month, events, tasks),
                           agenda.holiday_names(calendars, ids, days), agenda.off_days(calendars, ids, days))

    def _open_day(self, day):
        if self.controller:
            self.controller.show_day(day)

    # 舊名稱
    def update_calendar_highlights(self):
        self.refresh_events()


# --- 週曆橫條 ---

class WeekStrip(QWidget):
    """接下來 7 天：星期、日期、農曆、圓點。"""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.days = []
        self.items = {}
        self.off = set()
        self.holidays = {}
        self.setMouseTracking(True)

    def paintEvent(self, event):
        if not self.days:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.owner.pal
        kinds = DARK_KINDS if self.owner.dark else LIGHT_KINDS
        w = self.width() / len(self.days)
        h = self.height()
        today = date.today()
        base = QFont(self.owner.font_family)
        for i, d in enumerate(self.days):
            rect = QRectF(i * w + 2, 0, w - 4, h)
            key = d.isoformat()
            if d == today:
                path = QPainterPath()
                path.addRoundedRect(rect, 10, 10)
                soft = QColor(pal["accent"])
                soft.setAlpha(40)
                p.fillPath(path, soft)
            weekend = key in self.off
            head = QFont(base)
            head.setPixelSize(max(10, int(h * 0.15)))
            head.setBold(True)
            p.setFont(head)
            p.setPen(pal["accent"] if d == today else (pal["weekend"] if weekend else pal["muted"]))
            p.drawText(QRectF(rect.left(), rect.top() + 2, rect.width(), h * 0.24), Qt.AlignCenter,
                       "今天" if d == today else WEEKDAYS[d.weekday()])
            p.setFont(mono_font(h * 0.27))
            p.setPen(pal["weekend"] if weekend and d != today else pal["ink"])
            p.drawText(QRectF(rect.left(), rect.top() + h * 0.24, rect.width(), h * 0.34), Qt.AlignCenter, str(d.day))
            small = QFont(base)
            small.setPixelSize(max(9, int(h * 0.12)))
            p.setFont(small)
            holiday = self.holidays.get(key)
            text = holiday["name"] if holiday else short_lunar(d)
            p.setPen(pal["weekend"] if holiday and holiday.get("off") else pal["muted"])
            fm = QFontMetrics(small)
            p.drawText(QRectF(rect.left(), rect.top() + h * 0.58, rect.width(), h * 0.18), Qt.AlignCenter,
                       fm.elidedText(text, Qt.ElideRight, int(rect.width() - 4)))
            dots = self.items.get(key, [])[:3]
            r = max(2.2, h * 0.025)
            total = len(dots) * r * 2 + (len(dots) - 1) * 3
            x = rect.center().x() - total / 2 + r
            p.setPen(Qt.NoPen)
            for item in dots:
                p.setBrush(QColor(kinds[item["kind"]][2]))
                p.drawEllipse(QPointF(x, rect.top() + h * 0.86), r, r)
                x += r * 2 + 3

    def mouseMoveEvent(self, event):
        if not self.days:
            return
        index = int(event.position().x() // (self.width() / len(self.days)))
        if 0 <= index < len(self.days):
            d = self.days[index]
            lines = [f"<b>{d.month}/{d.day}（{WEEKDAYS[d.weekday()]}）</b> {lunar_text(d)}"]
            if d.isoformat() in self.holidays:
                lines.append(self.holidays[d.isoformat()]["name"])
            for item in self.items.get(d.isoformat(), []):
                lines.append(f"{item['time']} {item['title']}")
            QToolTip.showText(event.globalPosition().toPoint(), "<br>".join(lines), self)
        super().mouseMoveEvent(event)


class WeekFloat(FloatWindow):
    KEY, GEOMETRY = "week", "week_strip"
    DEFAULT_SIZE, MIN_SIZE = (480, 160), (320, 120)

    def build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(4)
        head = QHBoxLayout()
        self.title = QLabel("接下來 7 天")
        head.addWidget(self.title, 1)
        self.prev_btn = self.small_button("chevron_left", "前 7 天", lambda: self.shift(-7))
        self.next_btn = self.small_button("chevron_right", "後 7 天", lambda: self.shift(7))
        head.addWidget(self.prev_btn)
        head.addWidget(self.next_btn)
        layout.addLayout(head)
        self.strip = WeekStrip(self)
        layout.addWidget(self.strip, 1)
        self.next_row = QWidget()
        nr = QHBoxLayout(self.next_row)
        nr.setContentsMargins(4, 4, 4, 0)
        nr.setSpacing(8)
        self.next_bar = QWidget()
        self.next_bar.setFixedSize(4, 26)
        self.next_text = QLabel()
        self.next_when = QLabel()
        nr.addWidget(self.next_bar)
        nr.addWidget(self.next_text, 1)
        nr.addWidget(self.next_when)
        layout.addWidget(self.next_row)
        self.offset = 0
        self.refresh_events()

    def restyle(self):
        f = QFont(self.font_family)
        f.setPixelSize(13)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setStyleSheet(self.label_style())
        self.next_text.setStyleSheet(self.label_style())
        self.recolor_buttons()
        self.refresh_events()

    def shift(self, days):
        self.offset += days
        self.title.setText("接下來 7 天" if self.offset == 0 else f"{(date.today() + timedelta(days=self.offset)).strftime('%m/%d')} 起 7 天")
        self.refresh_events()

    def refresh_events(self):
        start = date.today() + timedelta(days=self.offset)
        days = [start + timedelta(days=i) for i in range(7)]
        events, tasks = self.data_manager.load_events(), self.data_manager.load_tasks()
        calendars = self.data_manager.load_holidays()
        ids = self.data_manager.load_billing().rule_for(None)["calendar_ids"]
        self.strip.days = days
        self.strip.items = {d.isoformat(): agenda.day_items(d, events, tasks) for d in days}
        self.strip.holidays = agenda.holiday_names(calendars, ids, days)
        self.strip.off = agenda.off_days(calendars, ids, days)
        self.strip.update()
        upcoming = tasks_service.upcoming_tasks(tasks, limit=1)
        if upcoming:
            t = upcoming[0]
            note, kind = tasks_service.due_info(t)
            color = self.pal["danger_hex"] if kind == "overdue" else (self.pal["warn_hex"] if kind in ("today", "soon") else self.pal["muted_hex"])
            self.next_bar.setStyleSheet(f"background: {color}; border-radius: 2px;")
            self.next_text.setText(f"下一個交件：{t.title}")
            self.next_when.setText(f"{t.due_date[5:].replace('-', '/')} {t.due_time} · {note}")
            self.next_when.setStyleSheet(self.label_style(bold=True, color=color))
            self.next_row.show()
        else:
            self.next_row.hide()


# --- 合併迷你條 ---

class MiniBarFloat(FloatWindow):
    KEY, GEOMETRY = "bar", "mini_bar"
    DEFAULT_SIZE, MIN_SIZE = (560, 52), (340, 40)
    RADIUS = 999

    def build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 4, 8, 4)
        layout.setSpacing(12)
        self.date = QLabel()
        self.clock = QLabel()
        self.sep1, self.sep2 = QWidget(), QWidget()
        self.pomo_dot, self.work_dot = Dot(), Dot()
        self.pomo = QLabel("25:00")
        self.pomo_phase = QLabel("")
        self.work = QLabel("00:00:00")
        self.main_btn = self.small_button("play", "開始／暫停番茄鐘", lambda: self.controller and self.controller.pomodoro_primary_action())
        for w in (self.sep1, self.sep2):
            w.setFixedWidth(1)
        layout.addWidget(self.date)
        layout.addWidget(self.clock)
        layout.addWidget(self.sep1)
        layout.addWidget(self.pomo_dot)
        layout.addWidget(self.pomo)
        layout.addWidget(self.pomo_phase)
        layout.addWidget(self.sep2)
        layout.addWidget(self.work_dot)
        layout.addWidget(self.work)
        layout.addStretch()
        layout.addWidget(self.main_btn)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.pomo_status = {"state": "idle", "remaining": 1500, "total": 1500}
        self.work_status = {"working": False, "current": 0, "total": 0, "sessions": 0}
        self.tick()

    def restyle(self):
        line = "rgba(255,255,255,0.16)" if self.dark else "rgba(51,38,29,0.14)"
        for w in (self.sep1, self.sep2):
            w.setStyleSheet(f"background: {line};")
        for lab in (self.clock, self.pomo, self.work):
            lab.setStyleSheet(self.label_style())
        self.pomo_phase.setStyleSheet(self.label_style(muted=True))
        self.date.setStyleSheet(self.label_style(muted=True))
        self.recolor_buttons()
        self.update_pomodoro(self.pomo_status)
        self.update_work(self.work_status)

    def rescale(self):
        h = self.height()
        for lab in (self.clock, self.pomo, self.work):
            lab.setFont(mono_font(h * 0.36))
        f = QFont(self.font_family)
        f.setPixelSize(max(11, int(h * 0.26)))
        self.pomo_phase.setFont(f)
        self.date.setFont(f)
        for w in (self.sep1, self.sep2):
            w.setFixedHeight(int(h * 0.42))
        need = self.layout().minimumSize().width()
        self.setMinimumWidth(max(self.MIN_SIZE[0], need))  # 字變大時不要把內容擠掉

    def tick(self):
        now = datetime.now()
        self.date.setText(f"{now.month}/{now.day}（{WEEKDAYS[now.weekday()]}）")
        self.clock.setText(now.strftime("%H:%M"))

    def update_pomodoro(self, status):
        self.pomo_status = status
        state = status["state"]
        self.pomo.setText(hms(status["remaining"], hours=False))
        self.pomo_phase.setText(PomodoroFloat.PHASES.get(state, ""))
        self.pomo_dot.set_color(self.pal["ok"] if state == "breaking" else (self.pal["muted"] if state in ("idle", "paused") else self.pal["accent"]))
        name = "pause" if state in ("working", "breaking") else "play"
        self.main_btn.setProperty("iconName", name)
        self.main_btn.setIcon(icon(name, self.pal["ink_hex"], 16))

    def update_work(self, status):
        self.work_status = status
        self.work.setText(hms(status["current"] if status["working"] else status["total"]))
        self.work_dot.set_color(self.pal["ok"] if status["working"] else self.pal["muted"])


ALL_FLOATS = {cls.KEY: cls for cls in (ClockFloat, CalendarFloat, WeekFloat, PomodoroFloat, WorkFloat, MiniBarFloat)}
