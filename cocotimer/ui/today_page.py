"""「今天」總覽：番茄鐘、打卡、本月收入、即將到期的任務、今日行程、懸浮工具開關。"""
from datetime import date, datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
                               QScrollArea, QSlider, QVBoxLayout, QWidget)

from cocotimer import tasks as tasks_service
from cocotimer.lunar import lunar_text
from cocotimer.ui.icons import icon
from cocotimer.ui.widgets import FlowLayout, button, card, icon_button, label, set_chip, set_tone

WEEKDAYS = "一二三四五六日"
CURRENCY_SYMBOLS = {"NTD": "NT$", "TWD": "NT$", "USD": "US$", "JPY": "¥", "EUR": "€", "CNY": "CN¥", "HKD": "HK$", "GBP": "£"}
DUE_CHIP = {"overdue": ("red", "逾期"), "today": ("amber", "今天交件"), "soon": ("amber", "快到了"), "normal": ("blue", "進行中")}


def money(currency: str, amount: float) -> str:
    return f"{CURRENCY_SYMBOLS.get(currency, currency + ' ')}{amount:,.0f}"


def money_lines(amounts: dict) -> str:
    return "、".join(money(c, a) for c, a in sorted(amounts.items())) or "0"


def hms(seconds: float, hours=True) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if hours else f"{h * 60 + m:02d}:{s:02d}"


def greeting(now: datetime) -> str:
    return "早安" if now.hour < 11 else "午安" if now.hour < 18 else "晚安"


class TaskRow(QFrame):
    """即將到期任務的一列，點一下開啟編輯。"""

    def __init__(self, task, on_open, parent=None):
        super().__init__(parent)
        self.setProperty("row", True)
        self.setCursor(Qt.PointingHandCursor)
        self.task_id = task.id
        self.on_open = on_open
        note, kind = tasks_service.due_info(task)
        chip_kind, chip_text = DUE_CHIP.get(kind, ("gray", "進行中"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(label(chip_text, chip=chip_kind))
        title = label(task.title, wrap=True)
        title.setStyleSheet("font-weight: 700;")
        title_row.addWidget(title, 1)
        left.addLayout(title_row)
        meta = " · ".join(p for p in (task.client, tasks_service.billing_summary(task)) if p)
        if meta:
            left.addWidget(label(meta, muted=True, wrap=True))
        top.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(3)
        amount = task.get_total_price()
        amount_label = label(money(task.currency or "NTD", amount) if amount else "")
        amount_label.setAlignment(Qt.AlignRight)
        amount_label.setStyleSheet("font-weight: 700;")
        due_label = label(f"{task.due_date[5:].replace('-', '/')} {task.due_time} · {note}", muted=kind not in ("overdue", "today"))
        due_label.setAlignment(Qt.AlignRight)
        due_label.setWordWrap(True)  # 窄的時候（側邊停靠）可以換行
        if kind in ("overdue", "today"):
            due_label.setProperty("tone", "danger" if kind == "overdue" else "warn")
        right.addWidget(amount_label)
        right.addWidget(due_label)
        top.addLayout(right)
        layout.addLayout(top)
        bar_row = QHBoxLayout()
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(task.completion)
        bar.setTextVisible(False)
        if kind == "overdue":
            bar.setProperty("danger", True)
        bar_row.addWidget(bar, 1)
        pct = label(f"{task.completion}%", role="mono", muted=True)
        pct.setMinimumWidth(40)
        pct.setAlignment(Qt.AlignRight)
        bar_row.addWidget(pct)
        layout.addLayout(bar_row)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_open(self.task_id)
        super().mouseReleaseEvent(event)


class TodayPage(QScrollArea):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.mw = main_window
        self.data_manager = main_window.data_manager
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("contentArea")
        self.setWidget(body)
        self.root = QVBoxLayout(body)
        self.root.setContentsMargins(28, 24, 28, 28)
        self.root.setSpacing(18)
        self._columns = None

        self._build_header()
        self._build_float_strip()
        self.pomodoro_card = self._build_pomodoro_card()
        self.work_card = self._build_work_card()
        self.income_card = self._build_income_card()
        self.tasks_card = self._build_tasks_card()
        self.events_card = self._build_events_card()
        self.grid = QGridLayout()
        self.grid.setSpacing(16)
        self.root.addLayout(self.grid)
        self.root.addStretch()
        self.refresh_all()

    # --- 版面 ---

    def _build_header(self):
        head = QBoxLayout(QBoxLayout.LeftToRight)
        head.setSpacing(12)
        self.header_layout = head
        text = QVBoxLayout()
        text.setSpacing(2)
        self.eyebrow = QLabel()
        self.eyebrow.setObjectName("pageEyebrow")
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.summary = label("", muted=True, wrap=True)
        text.addWidget(self.eyebrow)
        text.addWidget(self.title)
        text.addWidget(self.summary)
        head.addLayout(text, 1)
        self.add_event_btn = button("新增行程")
        self.add_event_btn.clicked.connect(lambda: self.mw.calendar_page.add_event(date.today()))
        self.add_task_btn = button("新增任務", primary=True)
        self.add_task_btn.clicked.connect(self.mw.add_task)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.add_event_btn)
        row.addWidget(self.add_task_btn)
        head.addLayout(row)
        head.setAlignment(row, Qt.AlignBottom)
        self.root.addLayout(head)

    def _build_float_strip(self):
        strip = card(spacing=10, margins=(16, 12, 16, 12))
        top = QHBoxLayout()
        top.addWidget(label("懸浮工具", role="h2"))
        top.addStretch()
        hide_all = button("全部隱藏", link=True)
        hide_all.clicked.connect(self.mw.hide_all_floats)
        top.addWidget(hide_all)
        strip.layout().addLayout(top)
        flow_holder = QWidget()
        flow = FlowLayout(flow_holder, spacing=8)
        self.float_buttons = {}
        for key, spec in self.mw.FLOAT_SPECS.items():
            btn = button(spec["name"], pill=True, checkable=True)
            btn.setIcon(icon(spec["icon"], self.mw.colors["muted"], 18))
            btn.toggled.connect(lambda on, k=key: self.mw.set_float_visible(k, on))
            flow.addWidget(btn)
            self.float_buttons[key] = btn
        strip.layout().addWidget(flow_holder)
        options = QHBoxLayout()
        options.setSpacing(16)
        self.float_lock = QCheckBox("鎖定位置")
        self.float_lock.setToolTip("鎖定後不能拖曳或縮放懸浮工具，避免不小心移動")
        self.float_lock.toggled.connect(lambda on: self.mw.set_floats_option(floats_locked=on))
        self.float_dark = QCheckBox("深色外觀")
        self.float_dark.toggled.connect(lambda on: self.mw.set_floats_option(floats_dark=on))
        options.addWidget(self.float_lock)
        options.addWidget(self.float_dark)
        options.addStretch()
        strip.layout().addLayout(options)
        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(10)
        opacity_row.addWidget(label("背景不透明度", muted=True))
        self.float_opacity = QSlider(Qt.Horizontal)
        self.float_opacity.setRange(20, 100)
        self.float_opacity.setSingleStep(5)
        self.float_opacity.setPageStep(10)
        self.float_opacity.setAccessibleName("懸浮工具背景不透明度")
        self.float_opacity_value = label("", role="mono", muted=True)
        self.float_opacity_value.setMinimumWidth(44)
        self.float_opacity_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._opacity_timer = QTimer(self)
        self._opacity_timer.setSingleShot(True)
        self._opacity_timer.setInterval(120)  # 拖動時稍微延遲再套用，避免每一格都寫檔
        self._opacity_timer.timeout.connect(lambda: self.mw.set_floats_option(floats_opacity=self.float_opacity.value()))
        self.float_opacity.valueChanged.connect(self._on_opacity_changed)
        opacity_row.addWidget(self.float_opacity, 1)
        opacity_row.addWidget(self.float_opacity_value)
        strip.layout().addLayout(opacity_row)
        self.root.addWidget(strip)

    def _build_pomodoro_card(self):
        c = card()
        head = QHBoxLayout()
        head.addWidget(label("番茄鐘", role="h2"))
        head.addStretch()
        self.pomo_chip = label("未開始", chip="gray")
        head.addWidget(self.pomo_chip)
        c.layout().addLayout(head)
        self.pomo_task = QComboBox()
        self.pomo_task.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.pomo_task.setMinimumContentsLength(8)
        self.pomo_task.setToolTip("專注時間會記到這個任務，任務對話框和統計頁會顯示累計時數與時薪")
        self.pomo_task.currentIndexChanged.connect(self._on_pomo_task_changed)
        c.layout().addWidget(self.pomo_task)
        self.pomo_time = label("25:00", role="timer")
        c.layout().addWidget(self.pomo_time)
        self.pomo_bar = QProgressBar()
        self.pomo_bar.setRange(0, 1000)
        self.pomo_bar.setTextVisible(False)
        c.layout().addWidget(self.pomo_bar)
        self.pomo_focus = label("", muted=True, wrap=True)
        c.layout().addWidget(self.pomo_focus)
        row = QHBoxLayout()
        self.pomo_main = button("開始專注", primary=True)
        self.pomo_main.clicked.connect(self.mw.pomodoro_primary_action)
        self.pomo_skip = icon_button("skip", self.mw.colors["muted"], "略過這一輪")
        self.pomo_skip.clicked.connect(self.mw.pomodoro_skip)
        self.pomo_reset = icon_button("reset", self.mw.colors["muted"], "停止並重設")
        self.pomo_reset.clicked.connect(self.mw.pomodoro_reset)
        row.addWidget(self.pomo_main, 1)
        row.addWidget(self.pomo_skip)
        row.addWidget(self.pomo_reset)
        c.layout().addLayout(row)
        return c

    def _build_work_card(self):
        c = card()
        head = QHBoxLayout()
        head.addWidget(label("打卡", role="h2"))
        head.addStretch()
        self.work_chip = label("未打卡", chip="gray")
        head.addWidget(self.work_chip)
        c.layout().addLayout(head)
        self.work_time = label("00:00:00", role="timerSmall")
        c.layout().addWidget(self.work_time)
        self.work_note = label("", muted=True, wrap=True)
        c.layout().addWidget(self.work_note)
        c.layout().addStretch()
        self.work_btn = button("上班打卡")
        self.work_btn.clicked.connect(self._toggle_work)
        c.layout().addWidget(self.work_btn)
        return c

    def _build_income_card(self):
        c = card()
        head = QHBoxLayout()
        self.income_title = label("本月收入", role="h2")
        head.addWidget(self.income_title)
        head.addStretch()
        stats = button("查看統計", link=True)
        stats.clicked.connect(lambda: self.mw.navigate("stats"))
        head.addWidget(stats)
        c.layout().addLayout(head)
        self.income_main = label("", role="money")
        c.layout().addWidget(self.income_main)
        self.income_paid = label("", wrap=True)
        self.income_expected = label("", wrap=True)
        self.income_overdue = label("", wrap=True)
        for w in (self.income_paid, self.income_expected, self.income_overdue):
            c.layout().addWidget(w)
        c.layout().addStretch()
        return c

    def _build_tasks_card(self):
        c = card(spacing=0)
        head = QHBoxLayout()
        head.addWidget(label("即將到期的任務", role="h2"))
        head.addStretch()
        more = button("全部任務", link=True)
        more.clicked.connect(lambda: self.mw.navigate("tasks"))
        head.addWidget(more)
        c.layout().addLayout(head)
        c.layout().addSpacing(6)
        self.tasks_list = QVBoxLayout()
        self.tasks_list.setSpacing(0)
        c.layout().addLayout(self.tasks_list)
        c.layout().addStretch()
        return c

    def _build_events_card(self):
        c = card(spacing=0)
        head = QHBoxLayout()
        head.addWidget(label("今日行程", role="h2"))
        head.addStretch()
        more = button("行事曆", link=True)
        more.clicked.connect(lambda: self.mw.navigate("events"))
        head.addWidget(more)
        c.layout().addLayout(head)
        c.layout().addSpacing(6)
        self.events_list = QVBoxLayout()
        self.events_list.setSpacing(0)
        c.layout().addLayout(self.events_list)
        c.layout().addStretch()
        self.water_label = label("", muted=True, wrap=True)
        c.layout().addSpacing(10)
        c.layout().addWidget(self.water_label)
        return c

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        width = self.viewport().width()
        self.header_layout.setDirection(QBoxLayout.LeftToRight if width >= 640 else QBoxLayout.TopToBottom)
        side = 28 if width >= 640 else 16
        self.root.setContentsMargins(side, 24, side, 28)
        columns = 3 if width >= 940 else 2 if width >= 520 else 1
        if columns == self._columns:
            return
        self._columns = columns
        for w in (self.pomodoro_card, self.work_card, self.income_card, self.tasks_card, self.events_card):
            self.grid.removeWidget(w)
        for col in range(3):
            self.grid.setColumnStretch(col, 0)
        if columns == 3:
            placements = [(self.pomodoro_card, 0, 0, 1, 1), (self.work_card, 0, 1, 1, 1), (self.income_card, 0, 2, 1, 1),
                          (self.tasks_card, 1, 0, 1, 2), (self.events_card, 1, 2, 1, 1)]
        elif columns == 2:
            placements = [(self.pomodoro_card, 0, 0, 1, 1), (self.work_card, 0, 1, 1, 1), (self.income_card, 1, 0, 1, 2),
                          (self.tasks_card, 2, 0, 1, 2), (self.events_card, 3, 0, 1, 2)]
        else:
            placements = [(w, i, 0, 1, 1) for i, w in enumerate(
                (self.pomodoro_card, self.work_card, self.tasks_card, self.events_card, self.income_card))]
        for widget, row, col, rs, cs in placements:
            self.grid.addWidget(widget, row, col, rs, cs)
        for col in range(columns):
            self.grid.setColumnStretch(col, 1)

    # --- 資料 ---

    def refresh_all(self):
        self.refresh_header()
        self.refresh_floats()
        self.refresh_tasks()
        self.refresh_events()
        self.refresh_income()
        self.tick()

    def tick(self):
        """每秒更新：番茄鐘、打卡計時、喝水提醒。"""
        self.refresh_pomodoro()
        self.refresh_work()
        self.refresh_water()

    def refresh_header(self):
        now = datetime.now()
        lunar = lunar_text(now.date())
        self.eyebrow.setText(f"{now.year} 年 {now.month} 月 {now.day} 日" + (f" · 農曆{lunar}" if lunar else ""))
        self.title.setText(f"星期{WEEKDAYS[now.weekday()]}，{greeting(now)}")

    def _on_opacity_changed(self, value):
        self.float_opacity_value.setText(f"{value}%")
        self._opacity_timer.start()

    def refresh_floats(self):
        settings = self.mw.settings
        if self.float_opacity.value() != settings.floats_opacity or not self.float_opacity_value.text():
            self.float_opacity.blockSignals(True)
            self.float_opacity.setValue(settings.floats_opacity)
            self.float_opacity.blockSignals(False)
            self.float_opacity_value.setText(f"{settings.floats_opacity}%")
        for box, on in ((self.float_lock, settings.floats_locked), (self.float_dark, settings.floats_dark)):
            if box.isChecked() != on:
                box.blockSignals(True)
                box.setChecked(on)
                box.blockSignals(False)
        for key, btn in self.float_buttons.items():
            visible = self.mw.float_visible(key)
            if btn.isChecked() != visible:
                btn.blockSignals(True)
                btn.setChecked(visible)
                btn.blockSignals(False)
            btn.setIcon(icon(self.mw.FLOAT_SPECS[key]["icon"],
                             self.mw.colors["accent_deep"] if visible else self.mw.colors["muted"], 18))

    def refresh_pomodoro(self):
        status = self.mw.pomodoro_status()
        state, remaining, total = status["state"], status["remaining"], status["total"]
        chips = {"idle": ("gray", "未開始"), "working": ("amber", "專注中"), "breaking": ("green", "休息中"),
                 "paused": ("gray", "已暫停")}
        set_chip(self.pomo_chip, *chips.get(state, chips["idle"]))
        self.pomo_time.setText(hms(remaining, hours=False))
        self.pomo_bar.setValue(int(1000 * (1 - remaining / total)) if total else 0)
        self.pomo_main.setText({"idle": "開始專注", "paused": "繼續"}.get(state, "暫停"))
        self.pomo_skip.setEnabled(state != "idle")
        self.pomo_reset.setEnabled(state != "idle")
        task = self.mw.pomodoro_task()
        if task is None:
            self.pomo_focus.setText("選一個任務，專注時間就會記到那個任務上。")
        else:
            seconds = tasks_service.focus_seconds(task)
            if self.mw._focus_started is not None:
                seconds += (datetime.now() - self.mw._focus_started).total_seconds()
            self.pomo_focus.setText(f"這個任務已專注 {tasks_service.focus_text(seconds)}" if seconds >= 60
                                    else "這個任務還沒有專注紀錄")

    def refresh_pomodoro_tasks(self):
        """專注任務的下拉選單：進行中的任務（依交件日）。目前選的任務不在進行中時也保留在清單裡。"""
        tasks = self.mw.task_page.tasks
        current = self.mw.pomodoro_task_id
        choices = tasks_service.sort_tasks([t for t in tasks if t.status == tasks_service.IN_PROGRESS], "due")
        if current and all(t.id != current for t in choices):
            choices += [t for t in tasks if t.id == current]
        self.pomo_task.blockSignals(True)
        self.pomo_task.clear()
        self.pomo_task.addItem("不指定任務", "")
        for t in choices:
            self.pomo_task.addItem(" · ".join(p for p in (t.title, t.client) if p), t.id)
        self.pomo_task.setCurrentIndex(max(0, self.pomo_task.findData(current)))
        self.pomo_task.blockSignals(False)

    def _on_pomo_task_changed(self, _index):
        self.mw.set_pomodoro_task(self.pomo_task.currentData() or "")

    def refresh_work(self):
        page = self.mw.work_page
        rec = page._get_today_record()
        working = page._is_working()
        total = rec.calculate_total_hours() * 3600
        if working:
            current = (datetime.now() - datetime.fromisoformat(rec.sessions[-1]["start"])).total_seconds()
            total += current
            set_chip(self.work_chip, "green", "工作中")
            self.work_time.setText(hms(current))
            start = rec.sessions[-1]["start"][11:16]
            self.work_note.setText(f"本段從 {start} 開始 · 今日累計 {int(total // 3600)} 小時 {int(total % 3600 // 60):02d} 分")
            self.work_btn.setText("下班打卡")
        else:
            set_chip(self.work_chip, "gray", "休息中" if rec.sessions else "未打卡")
            self.work_time.setText(hms(total))
            self.work_note.setText(f"今日累計 {len(rec.sessions)} 段" if rec.sessions else "今天還沒有打卡紀錄")
            self.work_btn.setText("上班打卡")

    def _toggle_work(self):
        self.mw.work_page.toggle_work()
        self.refresh_work()

    def refresh_water(self):
        timer = self.mw.water_timer
        if not self.mw.settings.water_reminder_enabled or not timer.isActive():
            self.water_label.setText("")
            return
        minutes = max(0, timer.remainingTime() // 60000)
        self.water_label.setText(f"下次喝水提醒：{minutes} 分鐘後 · 每 {self.mw.settings.water_reminder_interval} 分鐘")

    def refresh_tasks(self):
        self.refresh_pomodoro_tasks()
        tasks = self.data_manager.load_tasks()
        _clear(self.tasks_list)
        upcoming = tasks_service.upcoming_tasks(tasks)
        if not upcoming:
            self.tasks_list.addWidget(label("目前沒有進行中的任務。", muted=True))
        for task in upcoming:
            self.tasks_list.addWidget(TaskRow(task, self.mw.open_task))
        overdue = sum(1 for t in tasks if t.status == tasks_service.IN_PROGRESS and tasks_service.due_info(t)[1] == "overdue")
        due_today = sum(1 for t in tasks if t.status == tasks_service.IN_PROGRESS and tasks_service.due_info(t)[1] == "today")
        events_today = self._today_events()
        parts = [f"今天有 {len(events_today)} 個行程" if events_today else "今天沒有行程"]
        if due_today:
            parts.append(f"{due_today} 件任務今天要交")
        if overdue:
            parts.append(f"{overdue} 件已逾期")
        self.summary.setText("，".join(parts) + "。")

    def _today_events(self):
        today = date.today().isoformat()
        events = [e for e in self.data_manager.load_events() if e.date == today]
        return sorted(events, key=lambda e: e.time)

    def refresh_events(self):
        _clear(self.events_list)
        events = self._today_events()
        if not events:
            self.events_list.addWidget(label("今天沒有安排行程。", muted=True))
        now = datetime.now().strftime("%H:%M")
        for e in events:
            row = QFrame()
            row.setProperty("row", True)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 10, 0, 10)
            h.setSpacing(12)
            t = label(e.time, role="mono", muted=e.completed or e.time < now)
            t.setMinimumWidth(48)
            h.addWidget(t, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            title = label(e.title, wrap=True)
            title.setStyleSheet("text-decoration: line-through;" if e.completed else "font-weight: 700;")
            if e.completed:
                title.setProperty("muted", True)
            col.addWidget(title)
            if e.completed:
                col.addWidget(label("已完成", muted=True))
            elif e.description:
                col.addWidget(label(e.description.replace("\n", " ")[:40], muted=True))
            h.addLayout(col, 1)
            self.events_list.addWidget(row)

    def refresh_income(self):
        today = date.today()
        income = tasks_service.month_income(self.data_manager.load_tasks(), today.year, today.month, today)
        self.income_title.setText(f"{today.month} 月收入")
        paid, expected, overdue = income["paid"], income["expected"], income["overdue"]
        primary = "NTD" if "NTD" in {**paid, **expected} or not (paid or expected) else sorted({**paid, **expected})[0]
        self.income_main.setText(money(primary, paid.get(primary, 0) + expected.get(primary, 0)))
        self.income_paid.setText(f"已收款　{money_lines(paid)}")
        self.income_expected.setText(f"本月預計收款　{money_lines(expected)}")
        self.income_overdue.setVisible(bool(overdue))
        self.income_overdue.setText(f"逾期未收　{money_lines(overdue)}")
        set_tone(self.income_overdue, "danger")


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.hide()  # 立刻從畫面拿掉，不要等到 deleteLater 真正執行
            widget.setParent(None)
            widget.deleteLater()
