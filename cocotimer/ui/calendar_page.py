"""行事曆頁：月曆（行程、交件、假日在同一張）＋ 選取那天的詳情；也可以切到行程清單。"""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QMessageBox, QScrollArea, QVBoxLayout, QWidget)

from cocotimer import agenda
from cocotimer.lunar import lunar_text
from cocotimer.models import Event
from cocotimer.ui.dialogs import EventEditDialog
from cocotimer.ui.icons import icon
from cocotimer import theme as theme_module
from cocotimer.ui.month_view import DARK_KINDS, LIGHT_KINDS, MonthView
from cocotimer.ui.widgets import SegmentBar, button, card, icon_button, label

WEEKDAYS = "一二三四五六日"
WIDE = 860      # 比這個寬：月曆和當天詳情左右並排
COMPACT = 560   # 比這個窄：月曆改用圓點的精簡模式
PAST_LIMIT = 200


def _relative(day: date, today: date) -> str:
    diff = (day - today).days
    if diff == 0:
        return "今天"
    if diff == 1:
        return "明天"
    if diff == -1:
        return "昨天"
    return f"{diff} 天後" if diff > 0 else f"{-diff} 天前"


class AgendaRow(QFrame):
    """一個行程或交件：色條、時間、標題、說明。點一下開啟，行程可以按右鍵。"""

    def __init__(self, item, on_open, on_menu=None, show_kind=True, kinds=LIGHT_KINDS, parent=None):
        super().__init__(parent)
        self.item = item
        self.on_open = on_open
        self.on_menu = on_menu
        self.setProperty("row", True)
        self.setCursor(Qt.PointingHandCursor)
        kind = item["kind"]
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 10, 0, 10)
        h.setSpacing(10)
        bar = QFrame()
        bar.setFixedWidth(4)
        bar.setMinimumHeight(30)
        bar.setStyleSheet(f"background: {kinds[kind][2]}; border: none; border-radius: 2px;")
        h.addWidget(bar)
        time = label(item["time"] or "", role="mono", muted=True)
        time.setMinimumWidth(44)
        h.addWidget(time, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = label(item["title"], wrap=True)
        if kind == "done":
            title.setProperty("muted", True)
            title.setStyleSheet("text-decoration: line-through;")
        else:
            title.setStyleSheet("font-weight: 700;")
        col.addWidget(title)
        detail = (item.get("detail") or "").replace("\n", " ")
        if len(detail) > 60:
            detail = detail[:60] + "…"
        meta = " · ".join(p for p in ((agenda.KIND_LABELS[kind] if show_kind else ""), detail) if p)
        if meta:
            col.addWidget(label(meta, muted=True, wrap=True))
        h.addLayout(col, 1)
        tip = item.get("detail") or ""
        self.setToolTip(f"{item['title']}\n{tip}" if tip else item["title"])

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.on_open(self.item)
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        if self.on_menu:
            self.on_menu(self.item, event.globalPos())


class CalendarPage(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.mw = main_window
        self.data_manager = main_window.data_manager
        today = date.today()
        self.year, self.month = today.year, today.month
        self.selected = today
        self.mode = "month"
        self.list_range = "upcoming"
        self._wide = None
        self._build_ui()
        self.apply_colors()
        self.refresh()

    # --- 版面 ---

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
        self.root.setContentsMargins(28, 24, 28, 20)
        self.root.setSpacing(14)

        self.header = QBoxLayout(QBoxLayout.LeftToRight)
        self.header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("行事曆")
        title.setObjectName("pageTitle")
        self.summary = label("", muted=True, wrap=True)
        titles.addWidget(title)
        titles.addWidget(self.summary)
        self.header.addLayout(titles, 1)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.mode_bar = SegmentBar([("month", "月曆"), ("list", "清單")])
        self.mode_bar.set_current(self.mode)
        self.mode_bar.changed.connect(self.set_mode)
        add_btn = button("新增行程", primary=True)
        add_btn.clicked.connect(lambda: self.add_event())
        actions.addWidget(self.mode_bar)
        actions.addStretch()
        actions.addWidget(add_btn)
        self.header.addLayout(actions)
        self.root.addLayout(self.header)

        # 不用 QStackedWidget：它會把隱藏那一頁的最小寬度也算進來，窄視窗時會撐出畫面
        self.month_page = self._build_month_page()
        self.list_page = self._build_list_page()
        self.list_page.hide()
        self.root.addWidget(self.month_page, 1)
        self.root.addWidget(self.list_page, 1)

    def _build_month_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.prev_btn = icon_button("chevron_left", "#6E5B4E", "上個月")
        self.prev_btn.clicked.connect(lambda: self.shift(-1))
        self.next_btn = icon_button("chevron_right", "#6E5B4E", "下個月")
        self.next_btn.clicked.connect(lambda: self.shift(1))
        self.month_label = label("", role="h2")
        self.month_label.setStyleSheet("font-size: 18px;")
        today_btn = button("今天")
        today_btn.clicked.connect(self.go_today)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.month_label)
        nav.addWidget(self.next_btn)
        nav.addSpacing(6)
        nav.addWidget(today_btn)
        nav.addStretch()
        self.legend = QLabel()
        self.legend.setProperty("muted", True)
        nav.addWidget(self.legend)
        v.addLayout(nav)

        self.split = QBoxLayout(QBoxLayout.LeftToRight)
        self.split.setSpacing(16)
        self.month_card = card(margins=(8, 8, 8, 8))
        self.view = MonthView()
        self.view.selected.connect(self._on_day_clicked)
        self.view.activated.connect(lambda d: self.add_event(d))
        self.view.setToolTip("點一下看當天詳情，按兩下新增行程")
        self.month_card.layout().addWidget(self.view)
        self.split.addWidget(self.month_card, 1)

        self.day_card = card(spacing=4)
        self.day_title = label("", role="h2")
        self.day_title.setStyleSheet("font-size: 18px;")
        self.day_sub = label("", muted=True, wrap=True)
        self.day_card.layout().addWidget(self.day_title)
        self.day_card.layout().addWidget(self.day_sub)
        self.day_card.layout().addSpacing(6)
        self.day_list = QVBoxLayout()
        self.day_list.setSpacing(0)
        self.day_card.layout().addLayout(self.day_list)
        self.day_card.layout().addSpacing(8)
        self.add_on_day = button("＋ 在這天新增行程")
        self.add_on_day.clicked.connect(lambda: self.add_event(self.selected))
        self.day_card.layout().addWidget(self.add_on_day)
        self.day_card.layout().addStretch()
        self.split.addWidget(self.day_card)
        v.addLayout(self.split, 1)
        v.addStretch(0)
        self.month_v = v
        return page

    def _build_list_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.range_bar = SegmentBar([("upcoming", "即將到來"), ("past", "過去"), ("all", "全部")])
        self.range_bar.set_current(self.list_range)
        self.range_bar.changed.connect(self._set_range)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋行程標題或描述")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._render_list())
        self.show_done = QCheckBox("顯示已完成")
        self.show_done.toggled.connect(lambda _on: self._render_list())
        bar.addWidget(self.range_bar)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.show_done)
        self.list_bar = bar
        v.addLayout(bar)
        self.list_card = card(spacing=0)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(0)
        self.list_card.layout().addLayout(self.list_layout)
        v.addWidget(self.list_card)
        v.addStretch()
        return page

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        width = self.width()
        side = 28 if width >= 640 else 16
        self.root.setContentsMargins(side, 24, side, 20)
        self.header.setDirection(QBoxLayout.LeftToRight if width >= 640 else QBoxLayout.TopToBottom)
        self.legend.setVisible(width >= 700)
        self.list_bar.setDirection(QBoxLayout.LeftToRight if width >= 640 else QBoxLayout.TopToBottom)
        compact = width < COMPACT
        if compact != self.view.compact:
            self.view.set_compact(compact)
        wide = width >= WIDE
        if wide != self._wide:
            self._wide = wide
            self.split.setDirection(QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom)
            # 並排時月曆撐滿；上下排時月曆依格子大小決定高度，剩下的空間給當天詳情
            self.split.setStretchFactor(self.month_card, 1 if wide else 0)
            # 上下排時，多出來的高度放到最下面，不要拉長卡片或擠到月份標題上方
            self.month_v.setStretch(1, 1 if wide else 0)
            self.month_v.setStretch(2, 0 if wide else 1)
            if wide:
                self.day_card.setFixedWidth(300)
            else:
                self.day_card.setMinimumWidth(0)
                self.day_card.setMaximumWidth(16777215)
        self._fit_month_height()

    def _fit_month_height(self):
        """上下排（窄視窗、側邊停靠）時，讓月曆的格子接近正方形，不會因為螢幕很高就被拉得很長。"""
        if self._wide or self._wide is None:
            self.month_card.setMinimumHeight(0)
            self.month_card.setMaximumHeight(16777215)
            return
        side = 28 if self.width() >= 640 else 16
        inner = max(1, self.width() - 2 * side - 16)  # 卡片寬度扣掉內距（卡片本身可能還沒排好版）
        cell_w = inner / 7
        rows = max(1, len(self.view.days) // 7) or 6
        if self.view.compact:
            cell_h, head = max(54, min(cell_w * 1.05, 78)), 22
        else:
            cell_h, head = max(84, min(cell_w * 0.9, 120)), 30
        self.month_card.setFixedHeight(int(head + rows * cell_h + 16))

    def apply_colors(self):
        colors = self.mw.colors
        dark = theme_module.is_dark(colors)
        self.kinds = DARK_KINDS if dark else LIGHT_KINDS
        self.view.set_colors(colors, dark)
        self.legend.setText(" ".join(
            f"<span style='color:{self.kinds[k][2]}'>●</span> {agenda.KIND_LABELS[k]}&nbsp;&nbsp;"
            for k in ("event", "due", "overdue", "done")))
        for btn, name in ((self.prev_btn, "chevron_left"), (self.next_btn, "chevron_right")):
            btn.setIcon(icon(name, colors["muted"], 20))

    # --- 切換 ---

    def set_mode(self, mode):
        self.mode = mode
        self.mode_bar.set_current(mode)
        self.month_page.setVisible(mode == "month")
        self.list_page.setVisible(mode != "month")
        self.refresh()

    def _set_range(self, key):
        self.list_range = key
        self._render_list()

    def shift(self, months):
        index = self.year * 12 + self.month - 1 + months
        self.year, self.month = index // 12, index % 12 + 1
        today = date.today()
        self.selected = today if (today.year, today.month) == (self.year, self.month) else date(self.year, self.month, 1)
        self.refresh()

    def go_today(self):
        self.select_day(date.today())

    def select_day(self, day):
        """切到月曆並選取某一天（懸浮日曆按兩下時也會呼叫）。"""
        if self.mode != "month":
            self.mode = "month"
            self.mode_bar.set_current("month")
            self.month_page.show()
            self.list_page.hide()
        self.year, self.month, self.selected = day.year, day.month, day
        self.refresh()

    def _on_day_clicked(self, day):
        if (day.year, day.month) != (self.year, self.month):
            self.select_day(day)  # 點到前後月份補上的日子，就直接翻到那個月
            return
        self.selected = day
        self._render_day()

    # --- 資料 ---

    def _calendars(self):
        calendars = self.data_manager.load_holidays()
        ids = self.data_manager.load_billing().rule_for(None)["calendar_ids"]
        return calendars, ids

    def refresh(self):
        self.events = self.data_manager.load_events()
        self.tasks = self.data_manager.load_tasks()
        if self.mode == "list":
            self._render_list()
            self.summary.setText(f"共 {sum(1 for e in self.events if not e.completed and e.date >= date.today().isoformat())} 個即將到來的行程")
            return
        self.month_label.setText(f"{self.year} 年 {self.month} 月")
        self.view.set_month(self.year, self.month)
        calendars, ids = self._calendars()
        days = self.view.days
        items = agenda.month_items(self.year, self.month, self.events, self.tasks)
        self.holidays = agenda.holiday_names(calendars, ids, days)
        self.view.set_data(items, self.holidays, agenda.off_days(calendars, ids, days))
        self.view.set_selected(self.selected)
        self._fit_month_height()  # 這個月有 5 或 6 週
        self._render_day()

        prefix = f"{self.year:04d}-{self.month:02d}-"
        n_events = sum(1 for e in self.events if e.date.startswith(prefix))
        n_due = sum(1 for t in self.tasks if t.due_date.startswith(prefix))
        n_off = sum(1 for k, v in self.holidays.items() if k.startswith(prefix) and v.get("off"))
        parts = [f"{n_events} 個行程", f"{n_due} 件任務交件"]
        if n_off:
            parts.append(f"{n_off} 天放假")
        self.summary.setText(f"{self.month} 月：" + "、".join(parts))

    def _render_day(self):
        d = self.selected
        today = date.today()
        self.day_title.setText(f"{d.month} 月 {d.day} 日（{WEEKDAYS[d.weekday()]}）" + ("· 今天" if d == today else ""))
        sub = []
        holiday = getattr(self, "holidays", {}).get(d.isoformat())
        if holiday:
            sub.append(holiday["name"] + ("（放假）" if holiday.get("off") else ""))
        lunar = lunar_text(d)
        if lunar:
            sub.append(f"農曆{lunar}")
        if d != today:
            sub.append(_relative(d, today))
        self.day_sub.setText(" · ".join(sub))
        _clear(self.day_list)
        items = agenda.day_items(d, self.events, self.tasks)
        if not items:
            self.day_list.addWidget(label("這天沒有安排。", muted=True))
        for item in items:
            self.day_list.addWidget(AgendaRow(item, self._open_item, self._item_menu, kinds=self.kinds))

    def _render_list(self):
        _clear(self.list_layout)
        today = date.today()
        key = today.isoformat()
        words = self.search.text().lower().split()
        events = [e for e in self.data_manager.load_events()
                  if (self.show_done.isChecked() or not e.completed)
                  and all(w in f"{e.title} {e.description}".lower() for w in words)]
        if self.list_range == "upcoming":
            events = sorted((e for e in events if e.date >= key), key=lambda e: (e.date, e.time))
        elif self.list_range == "past":
            events = sorted((e for e in events if e.date < key), key=lambda e: (e.date, e.time), reverse=True)
        else:
            events = sorted(events, key=lambda e: (e.date, e.time))
        hidden = max(0, len(events) - PAST_LIMIT) if self.list_range != "upcoming" else 0
        if hidden:
            events = events[:PAST_LIMIT]
        if not events:
            self.list_layout.addWidget(label("沒有符合的行程。", muted=True))
            return
        current = None
        for e in events:
            if e.date != current:
                current = e.date
                try:
                    d = date.fromisoformat(e.date)
                    text = f"{d.month}/{d.day}（{WEEKDAYS[d.weekday()]}）　{_relative(d, today)}"
                except ValueError:
                    text = e.date
                head = label(text, muted=True)
                head.setStyleSheet("font-weight: 700; padding-top: 12px; padding-bottom: 2px;")
                self.list_layout.addWidget(head)
            item = {"kind": "done" if e.completed else "event", "time": e.time, "title": e.title,
                    "detail": e.description, "ref": e}
            self.list_layout.addWidget(AgendaRow(item, self._open_item, self._item_menu, show_kind=False,
                                                 kinds=self.kinds))
        if hidden:
            self.list_layout.addWidget(label(f"另有 {hidden} 個較舊的行程沒有顯示，可以用搜尋找找看。", muted=True))

    # --- 行程操作 ---

    def _open_item(self, item):
        ref = item["ref"]
        if isinstance(ref, Event):
            self.edit_event(ref.id)
        else:
            self.mw.open_task(ref.id)

    def _item_menu(self, item, pos):
        ref = item["ref"]
        is_event = isinstance(ref, Event)
        menu = QMenu(self)
        open_action = menu.addAction("編輯行程…" if is_event else "開啟任務…")
        done_action = delete_action = None
        if is_event:
            done_action = menu.addAction("取消完成" if ref.completed else "標記為已完成")
            menu.addSeparator()
            delete_action = menu.addAction("刪除行程")
        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen is open_action:
            self._open_item(item)
        elif chosen is done_action:
            self.set_event_completed(ref.id, not ref.completed)
        elif chosen is delete_action:
            if QMessageBox.question(self, "刪除行程", f"確定要刪除「{ref.title}」嗎？",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
                self.delete_event(ref)

    def add_event(self, day=None):
        dialog = EventEditDialog(self.data_manager, None, self, preset_date=day or self.selected)
        if dialog.exec() == QDialog.Accepted:
            events = self.data_manager.load_events()
            events.append(dialog.get_event())
            self.data_manager.save_events(events)
            self._after_change()

    def edit_event(self, event_id):
        events = self.data_manager.load_events()
        target = next((e for e in events if e.id == event_id), None)
        if target is None:
            return
        dialog = EventEditDialog(self.data_manager, target, self, on_delete=self.delete_event)
        if dialog.exec() == QDialog.Accepted:
            self.data_manager.save_events(events)
            self._after_change()

    def delete_event(self, event):
        events = [e for e in self.data_manager.load_events() if e.id != event.id]
        self.data_manager.save_events(events)
        self._after_change()

    def set_event_completed(self, event_id, done):
        events = self.data_manager.load_events()
        for e in events:
            if e.id == event_id:
                e.completed = done
        self.data_manager.save_events(events)
        self._after_change()

    def _after_change(self):
        self.mw.check_notifications()
        self.mw.refresh_overview_events()  # 也會更新這一頁（見 MainWindow.refresh_calendars）


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
