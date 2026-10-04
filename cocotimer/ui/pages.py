"""打卡紀錄頁。"""
from datetime import datetime, timedelta

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

from cocotimer.models import WorkRecord
from cocotimer.ui.widgets import button, card, label, set_chip


WEEKDAYS = "一二三四五六日"


def _hms(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _hours_text(seconds):
    minutes = int(seconds // 60)
    return f"{minutes // 60} 小時 {minutes % 60:02d} 分"


class WorkPage(QWidget):
    """打卡紀錄：今天的打卡狀態、今天的每一段紀錄、最近 7 天的工時。"""

    def __init__(self, data_manager, main_window=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.main_window = main_window
        self.work_records = self.data_manager.load_work_records()
        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self._update_live_display)
        self.pomodoro_update_timer = QTimer(self)
        self.pomodoro_update_timer.timeout.connect(self._update_pomodoro_display)
        self._build_ui()
        self._refresh_ui_states()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("contentArea")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.root = QVBoxLayout(body)
        self.root.setContentsMargins(28, 24, 28, 28)
        self.root.setSpacing(16)

        title = QLabel("打卡紀錄")
        title.setObjectName("pageTitle")
        self.root.addWidget(title)
        self.summary = label("", muted=True, wrap=True)
        self.root.addWidget(self.summary)

        today = card(spacing=8)
        head = QHBoxLayout()
        head.addWidget(label("今天", role="h2"))
        head.addStretch()
        self.state_chip = label("未打卡", chip="gray")
        head.addWidget(self.state_chip)
        today.layout().addLayout(head)
        self.timer_label = label("00:00:00", role="timerSmall")
        today.layout().addWidget(self.timer_label)
        self.today_total_label = label("", muted=True, wrap=True)
        self.current_status_label = self.today_total_label  # 舊名稱
        today.layout().addWidget(self.today_total_label)
        self.pomodoro_status_label = label("", muted=True, wrap=True)
        today.layout().addWidget(self.pomodoro_status_label)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.btn_toggle_work = button("上班打卡", primary=True)
        self.btn_toggle_work.clicked.connect(self.toggle_work)
        self.btn_pomodoro = button("開始番茄鐘")
        if self.main_window:
            self.btn_pomodoro.clicked.connect(self.main_window.toggle_pomodoro)
        buttons.addWidget(self.btn_toggle_work, 1)
        buttons.addWidget(self.btn_pomodoro, 1)
        today.layout().addSpacing(4)
        today.layout().addLayout(buttons)
        self.root.addWidget(today)

        sessions = card(spacing=0)
        sessions.layout().addWidget(label("今天的每一段", role="h2"))
        sessions.layout().addSpacing(6)
        self.history_list = QVBoxLayout()
        self.history_list.setSpacing(0)
        sessions.layout().addLayout(self.history_list)
        self.root.addWidget(sessions)

        week = card(spacing=0)
        week.layout().addWidget(label("最近 7 天", role="h2"))
        week.layout().addWidget(label("點一下可以修改那天的打卡時間；更早的紀錄在「統計」頁。", muted=True, wrap=True))
        week.layout().addSpacing(6)
        self.week_list = QVBoxLayout()
        self.week_list.setSpacing(0)
        week.layout().addLayout(self.week_list)
        self.root.addWidget(week)
        self.root.addStretch()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        side = 28 if self.width() >= 640 else 16
        self.root.setContentsMargins(side, 24, side, 28)

    # --- 資料 ---

    def _get_today_record(self) -> WorkRecord:
        today_str = datetime.now().strftime("%Y-%m-%d")
        return self.work_records.setdefault(today_str, WorkRecord(date=today_str))

    def _is_working(self) -> bool:
        rec = self._get_today_record()
        if not rec.sessions: return False
        return rec.sessions[-1].get('end') is None

    def toggle_work(self):
        if self._is_working():
            rec = self._get_today_record()
            rec.sessions[-1]['end'] = datetime.now().isoformat()
            self.live_timer.stop()
        else:
            rec = self._get_today_record()
            rec.sessions.append({'start': datetime.now().isoformat(), 'end': None})
            self.live_timer.start(1000)
        self.data_manager.save_work_records(self.work_records)
        self._refresh_ui_states()

    def _refresh_ui_states(self):
        self.work_records = self.data_manager.load_work_records()
        working = self._is_working()
        self.btn_toggle_work.setText("下班打卡" if working else "上班打卡")
        if working:
            self.live_timer.start(1000)
        else:
            self.live_timer.stop()
        self._update_live_display()
        self._update_history_list()
        self._update_week()
        if self.main_window:
            self.main_window.update_work_status_label()
            if self.main_window.pomodoro_state != "idle":
                self.pomodoro_update_timer.start(1000)
            else:
                self.pomodoro_update_timer.stop()
            self._update_pomodoro_display()

    def _update_live_display(self):
        rec = self._get_today_record()
        total = rec.calculate_total_hours() * 3600
        if self._is_working():
            current = max(0.0, (datetime.now() - datetime.fromisoformat(rec.sessions[-1]['start'])).total_seconds())
            total += current
            set_chip(self.state_chip, "green", "工作中")
            self.timer_label.setText(_hms(current))
            self.today_total_label.setText(
                f"這一段從 {rec.sessions[-1]['start'][11:16]} 開始 · 今日累計 {_hours_text(total)}")
        else:
            set_chip(self.state_chip, "gray", "休息中" if rec.sessions else "未打卡")
            self.timer_label.setText(_hms(total))
            self.today_total_label.setText(f"今日累計 {_hours_text(total)} · {len(rec.sessions)} 段" if rec.sessions
                                           else "今天還沒有打卡紀錄")
        self.summary.setText(f"今天已工作 {_hours_text(total)}" if total else "按「上班打卡」開始記錄今天的工時。")

    def _update_pomodoro_display(self):
        status = self.main_window.pomodoro_status() if self.main_window else {"state": "idle"}
        state = status["state"]
        if state == "idle":
            self.pomodoro_status_label.setText("番茄鐘：未開始")
            return
        names = {"working": "專注中", "breaking": "休息中", "paused": "已暫停"}
        minutes, seconds = divmod(int(status.get("remaining", 0)), 60)
        self.pomodoro_status_label.setText(f"番茄鐘：{names.get(state, '')} {minutes:02d}:{seconds:02d}")

    def start_pomodoro_timer(self):
        """啟動番茄鐘狀態的每秒更新（由主視窗呼叫）"""
        self.pomodoro_update_timer.start(1000)
        self._update_pomodoro_display()

    def stop_pomodoro_timer(self):
        self.pomodoro_update_timer.stop()
        self._update_pomodoro_display()

    def _update_history_list(self):
        _clear_layout(self.history_list)
        rec = self._get_today_record()
        if not rec.sessions:
            self.history_list.addWidget(label("今天還沒有打卡紀錄。", muted=True))
            return
        for i, session in enumerate(rec.sessions):
            start = datetime.fromisoformat(session['start'])
            end = datetime.fromisoformat(session['end']) if session.get('end') else None
            row = QFrame()
            row.setProperty("row", True)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 10, 0, 10)
            h.setSpacing(12)
            h.addWidget(label(f"第 {i + 1} 段", muted=True))
            h.addWidget(label(f"{start:%H:%M} – {end:%H:%M}" if end else f"{start:%H:%M} –", role="mono"), 1)
            if end:
                h.addWidget(label(_hours_text((end - start).total_seconds())))
            else:
                chip = label("工作中", chip="green")
                h.addWidget(chip)
            self.history_list.addWidget(row)

    def _update_week(self):
        _clear_layout(self.week_list)
        today = datetime.now().date()
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        totals = []
        for d in days:
            rec = self.work_records.get(d.isoformat())
            seconds = rec.calculate_total_hours() * 3600 if rec else 0
            if rec and d == today and self._is_working():
                seconds += max(0.0, (datetime.now() - datetime.fromisoformat(rec.sessions[-1]['start'])).total_seconds())
            totals.append(seconds)
        peak = max(totals) or 1
        for d, seconds in zip(days, totals):
            row = _ClickableRow(lambda ds=d.isoformat(): self.main_window and self.main_window.edit_work_day(ds))
            row.setToolTip("點一下可以修改這天的打卡時間" if seconds else "")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 8, 0, 8)
            h.setSpacing(10)
            name = label("今天" if d == today else f"{d.month}/{d.day}（{WEEKDAYS[d.weekday()]}）", muted=d != today)
            name.setMinimumWidth(QFontMetrics(name.font()).horizontalAdvance("12/30（三）") + 6)  # 每一列的長條對齊
            h.addWidget(name)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(1000 * seconds / peak))
            bar.setTextVisible(False)
            bar.setMinimumWidth(40)
            h.addWidget(bar, 1)
            value = label(f"{seconds / 3600:.1f} 小時" if seconds else "—", role="mono", muted=not seconds)
            value.setMinimumWidth(70)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(value)
            self.week_list.addWidget(row)


class _ClickableRow(QFrame):
    def __init__(self, on_click):
        super().__init__()
        self.setProperty("row", True)
        self.on_click = on_click
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.on_click()
        super().mouseReleaseEvent(event)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
