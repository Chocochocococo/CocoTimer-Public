"""統計頁：收入、待收款、交付件數、工時、番茄鐘專注，依月、依年或全部一起看；可以匯出 Excel／CSV。"""
from datetime import date

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QBoxLayout, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QMessageBox, QProgressBar, QScrollArea, QVBoxLayout, QWidget)

from cocotimer import currency as currency_module
from cocotimer import stats
from cocotimer import theme as theme_module
from cocotimer import tasks as tasks_service
from cocotimer.ui.charts import BarChart
from cocotimer.ui.icons import icon
from cocotimer.ui.today_page import money, money_lines
from cocotimer.ui.widgets import SegmentBar, button, card, icon_button, label, set_tone

WEEKDAYS = "一二三四五六日"
TASK_LIMIT = 60
TILES = (("income", "已收款"), ("average", "每月平均收入"), ("receivable", "待收款"), ("delivered", "交付"), ("work", "工時"))
CONVERTED = "*"  # 收款圖的「全部換算成常用幣別」
MONTHLY_BARS_UP_TO = 36  # 「全部」的圖表：三年以內一個月一根，更長就一年一根


def _amounts(amounts: dict) -> str:
    """好幾種幣別的金額；在「、」後面加上可以換行的位置，窄的時候一種幣別一行。"""
    return money_lines(amounts).replace("、", "、\u200b")


def _hours(seconds: float) -> str:
    hours = seconds / 3600
    return f"{hours:.1f} 小時" if hours < 100 else f"{hours:,.0f} 小時"


def _months_text(keys) -> str:
    """["2025-10", …, "2026-09"] → "2025/10–2026/9，12 個月"。"""
    (y1, m1), (y2, m2) = [(int(k[:4]), int(k[5:7])) for k in (keys[0], keys[-1])]
    if keys[0] == keys[-1]:
        span = f"{y1}/{m1}"
    elif y1 == y2:
        span = f"{y1}/{m1}–{m2} 月"
    else:
        span = f"{y1}/{m1}–{y2}/{m2}"
    return f"{span}，{len(keys)} 個月"


class _Row(QFrame):
    """可以點的一列；右鍵時呼叫 on_menu。"""

    def __init__(self, on_click=None, on_menu=None):
        super().__init__()
        self.setProperty("row", True)
        self.on_click, self.on_menu = on_click, on_menu
        if on_click:
            self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if self.on_click and event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.on_click()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        if self.on_menu:
            self.on_menu(event.globalPos())


class StatsPage(QScrollArea):
    """統計頁。popup=True 是放在獨立視窗裡的那一份（不再顯示「在新視窗開啟」）。"""

    def __init__(self, main_window, parent=None, popup=False):
        super().__init__(parent)
        self.mw = main_window
        self.popup = popup
        self.popout_btn = None
        self.data_manager = main_window.data_manager
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        today = date.today()
        self.kind = "month"
        self.year, self.month = today.year, today.month
        self.currency = None
        self.base, self.rates = "NTD", {}
        self.task_limit = TASK_LIMIT
        self._range = stats.period(self.kind, self.year, self.month)
        self._columns = None
        body = QWidget()
        body.setObjectName("contentArea")
        self.setWidget(body)
        self.root = QVBoxLayout(body)
        self.root.setContentsMargins(28, 24, 28, 28)
        self.root.setSpacing(16)
        self._build()

    # --- 版面 ---

    def _build(self):
        self.header = QBoxLayout(QBoxLayout.LeftToRight)
        self.header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("統計")
        title.setObjectName("pageTitle")
        titles.addWidget(title)
        self.header.addLayout(titles, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.kind_bar = SegmentBar([("month", "月"), ("year", "年"), ("all", "全部")])
        self.kind_bar.set_current(self.kind)
        self.kind_bar.changed.connect(self._set_kind)
        export_btn = button("匯出…")
        menu = QMenu(export_btn)
        menu.addAction("匯出這段期間", lambda: self.export(False))
        menu.addAction("匯出全部資料", lambda: self.export(True))
        export_btn.setMenu(menu)
        actions.addWidget(self.kind_bar)
        actions.addStretch()
        actions.addWidget(export_btn)
        if not self.popup:
            self.popout_btn = icon_button("popout", "#6E5B4E", "在新視窗開啟統計")
            self.popout_btn.clicked.connect(self.mw.open_stats_window)
            actions.addWidget(self.popout_btn)
        self.header.addLayout(actions)
        self.root.addLayout(self.header)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.nav = nav
        self.prev_btn = icon_button("chevron_left", "#6E5B4E", "上一段")
        self.prev_btn.clicked.connect(lambda: self.shift(-1))
        self.next_btn = icon_button("chevron_right", "#6E5B4E", "下一段")
        self.next_btn.clicked.connect(lambda: self.shift(1))
        self.period_label = label("", role="h2")
        self.period_label.setStyleSheet("font-size: 18px;")
        self.now_btn = button("本月")
        self.now_btn.clicked.connect(self.go_now)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.period_label)
        nav.addWidget(self.next_btn)
        nav.addSpacing(6)
        nav.addWidget(self.now_btn)
        nav.addStretch()
        self.root.addLayout(nav)

        self.tiles = {}
        self.tile_grid = QGridLayout()
        self.tile_grid.setSpacing(12)
        for key, title_text in TILES:
            c = card(spacing=4, margins=(18, 14, 18, 14))
            c.layout().addWidget(label(title_text, muted=True))
            value = label("", wrap=True)
            value.setStyleSheet("font-size: 22px; font-weight: 700;")
            sub = label("", muted=True, wrap=True)
            detail = label("", muted=True, wrap=True)  # 換算前各幣別的金額，字小一點
            detail.setStyleSheet("font-size: 12px;")
            detail.setTextFormat(Qt.RichText)
            detail.linkActivated.connect(self._open_rates)
            for w in (value, sub, detail):
                c.layout().addWidget(w)
            c.layout().addStretch()
            self.tiles[key] = (c, value, sub, detail)
        self.root.addLayout(self.tile_grid)

        self.income_card = card(spacing=8)
        head = QHBoxLayout()
        self.income_title = label("", role="h2", wrap=True)
        head.addWidget(self.income_title, 1)
        self.currency_input = QComboBox()
        self.currency_input.currentIndexChanged.connect(self._set_currency)
        head.addWidget(self.currency_input)
        self.income_card.layout().addLayout(head)
        self.income_chart = BarChart()
        self.income_card.layout().addWidget(self.income_chart)
        self.work_card = card(spacing=8)
        self.work_title = label("", role="h2", wrap=True)
        self.work_card.layout().addWidget(self.work_title)
        self.work_chart = BarChart()
        self.work_card.layout().addWidget(self.work_chart)
        self.chart_grid = QGridLayout()
        self.chart_grid.setSpacing(16)
        self.root.addLayout(self.chart_grid)

        self.clients_card, self.clients_list = self._list_card("客戶")
        self.tasks_card, self.tasks_list = self._list_card("任務")
        self.more_btn = button("")
        self.more_btn.clicked.connect(self._show_more)
        self.tasks_card.layout().addWidget(self.more_btn, 0, Qt.AlignLeft)
        self.tasks_hint = label("點一下任務可以編輯。專注時間來自番茄鐘（在「今天」選擇要專注的任務）。", muted=True, wrap=True)
        self.tasks_card.layout().addWidget(self.tasks_hint)
        self.days_card, self.days_list = self._list_card("打卡紀錄")
        self.days_card.layout().addWidget(label("點一下可以修改那天的打卡時間，右鍵可以刪除。", muted=True, wrap=True))
        for c in (self.clients_card, self.tasks_card, self.days_card):
            self.root.addWidget(c)
        self.root.addStretch()

    def _list_card(self, title):
        c = card(spacing=0)
        c.layout().addWidget(label(title, role="h2"))
        c.layout().addSpacing(6)
        lst = QVBoxLayout()
        lst.setSpacing(0)
        c.layout().addLayout(lst)
        return c, lst

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        width = self.viewport().width()
        side = 28 if width >= 640 else 16
        self.root.setContentsMargins(side, 24, side, 28)
        self.header.setDirection(QBoxLayout.LeftToRight if width >= 640 else QBoxLayout.TopToBottom)
        # 寬的時候一排五張；中等寬度三張一排（第一排是錢、第二排是工作量）；再窄就兩張、一張
        options = [n for n in (5, 3, 2, 1) if width >= {5: 1100, 3: 640, 2: 440, 1: 0}[n]]
        need = max(self.tiles[k][0].minimumSizeHint().width() for k in self.tiles)
        columns = next((n for n in options if (width - 2 * side - 12 * (n - 1)) / n >= need), 1)
        if columns == self._columns:
            return
        self._columns = columns
        for i, (key, _title) in enumerate(TILES):
            c = self.tiles[key][0]
            self.tile_grid.removeWidget(c)
            self.tile_grid.addWidget(c, i // columns, i % columns)
        for col in range(5):
            self.tile_grid.setColumnStretch(col, 1 if col < columns else 0)
        for w in (self.income_card, self.work_card):
            self.chart_grid.removeWidget(w)
        side_by_side = width >= 1000
        self.chart_grid.addWidget(self.income_card, 0, 0)
        self.chart_grid.addWidget(self.work_card, 0 if side_by_side else 1, 1 if side_by_side else 0)
        self.chart_grid.setColumnStretch(0, 1)
        self.chart_grid.setColumnStretch(1, 1 if side_by_side else 0)

    def apply_colors(self):
        colors = self.mw.colors
        for chart in (self.income_chart, self.work_chart):
            chart.set_colors(colors)
        for btn, name in ((self.prev_btn, "chevron_left"), (self.next_btn, "chevron_right"), (self.popout_btn, "popout")):
            if btn is not None:
                btn.setIcon(icon(name, colors["muted"], 20))

    # --- 切換 ---

    def _set_kind(self, kind):
        self.kind = kind
        self.task_limit = TASK_LIMIT
        self.now_btn.setText("本月" if kind == "month" else "今年")
        for w in (self.prev_btn, self.next_btn, self.now_btn):
            w.setVisible(kind != "all")
        self.refresh()

    def _show_more(self):
        self.task_limit += TASK_LIMIT
        self._refresh_tasks(self.data_manager.load_tasks(), *self._range)

    def shift(self, step):
        if self.kind == "year":
            self.year += step
        else:
            index = self.year * 12 + self.month - 1 + step
            self.year, self.month = index // 12, index % 12 + 1
        self.task_limit = TASK_LIMIT
        self.refresh()

    def go_now(self):
        today = date.today()
        self.year, self.month = today.year, today.month
        self.refresh()

    def _open_rates(self, _link=""):
        self.mw.restore_from_tray()
        self.mw.navigate("settings")
        self.mw.settings_page.focus_rates()

    def _set_currency(self, _index):
        cur = self.currency_input.currentData()
        if cur and cur != self.currency:
            self.currency = cur
            self.refresh()

    # --- 資料 ---

    def refresh(self):
        tasks = self.data_manager.load_tasks()
        records = self.data_manager.load_work_records()
        if self.kind == "all":
            start, end = stats.data_span(tasks, records)
            name = "全部紀錄"
            self.period_label.setText(f"{int(start[:4])} 年 {int(start[5:7])} 月至今")
        else:
            start, end = stats.period(self.kind, self.year, self.month)
            name = f"{self.year} 年" if self.kind == "year" else f"{self.year} 年 {self.month} 月"
            self.period_label.setText(name)
        self._range = (start, end)
        self.apply_colors()

        settings = self.data_manager.load_settings()
        self.base, self.rates = settings.default_currency or "NTD", settings.exchange_rates
        first = stats.data_span(tasks, records)[0]

        paid = stats.income(tasks, start, end)
        due = stats.expected(tasks, start, end)
        receivable, late = stats.receivable(tasks)
        delivered = stats.delivered_count(tasks, start, end)
        in_progress = sum(1 for t in tasks if t.status == tasks_service.IN_PROGRESS)
        work_days = stats.work_by_day(records, start, end)
        work_total = sum(v for _d, v in work_days)
        focus = stats.focus_total(tasks, start, end)

        self._set_tile("income", paid, f"預計還會收 {self._money(due)[0]}" if due and self.kind != "all" else "依實際收款日計算")
        months = stats.average_months(self.kind, self.year, self.month, first)
        if months:
            total = stats.income(tasks, *stats.months_period(months))
            self._set_tile("average", {c: v / len(months) for c, v in total.items()}, _months_text(months),
                           breakdown=False)
        else:
            self._set_tile("average", {}, "")
        self._set_tile("receivable", receivable,
                       f"逾期未收 {self._money(late)[0]}" if late else "不分期間，目前所有未收的款項")
        set_tone(self.tiles["receivable"][2], "danger" if late else "")
        _c, value, sub, _d = self.tiles["delivered"]
        value.setText(f"{delivered} 件")
        sub.setText(f"目前進行中 {in_progress} 件")
        _c, value, sub, _d = self.tiles["work"]
        value.setText(_hours(work_total))
        days_worked = sum(1 for _d, v in work_days if v > 0)
        sub.setText(" · ".join(p for p in (f"打卡 {days_worked} 天" if days_worked else "",
                                           f"番茄鐘專注 {_hours(focus)}" if focus >= 60 else "") if p) or "這段期間沒有打卡")

        self._relayout()
        self._refresh_income_chart(tasks, start, end)
        self._refresh_work_chart(records, work_days, start, end)
        self._refresh_clients(tasks, start, end)
        self._refresh_tasks(tasks, start, end)
        self._refresh_days(work_days)

    def _money(self, amounts):
        """（大數字, 小字明細）。好幾種幣別時用設定的匯率換算成常用幣別；缺匯率的幣別列在明細裡。"""
        if not amounts:
            return money(self.base, 0), ""
        if len(amounts) == 1:
            (cur, value), = amounts.items()
            return money(cur, value), ""
        total, missing = currency_module.convert(amounts, self.base, self.rates)
        every = "、".join(money(c, v) for c, v in sorted(amounts.items(), key=lambda kv: (kv[0] != self.base, kv[0])))
        if not missing:
            return f"≈ {money(self.base, total)}", every
        if len(missing) == len(amounts):  # 一個都換算不了
            return _amounts(amounts), f'<a href="rates">設定匯率</a>就能合併成一個數字'
        converted = len(amounts) - len(missing) > 1 or self.base not in amounts
        rest = "、".join(money(c, amounts[c]) for c in missing)
        return (("≈ " if converted else "") + money(self.base, total),
                f'另有 {rest}（<a href="rates">設定匯率</a>）')

    def _set_tile(self, key, amounts, sub_text, breakdown=True):
        _c, value, sub, detail = self.tiles[key]
        head, extra = self._money(amounts)
        if not breakdown and "rates" not in extra:  # 只留「缺匯率」的提醒，不列各幣別明細
            extra = ""
        value.setText(head if amounts or key != "average" else "—")
        sub.setText(sub_text)
        sub.setVisible(bool(sub_text))
        detail.setText(extra)
        detail.setVisible(bool(extra))

    def _span_keys(self, start, end):
        """「全部」的圖表要畫哪些月份或年份，以及標籤和提示文字。"""
        keys = stats.month_keys(start, end)
        if len(keys) <= MONTHLY_BARS_UP_TO:
            return keys, [f"{int(k[:4])}/{int(k[5:])}" for k in keys], [f"{int(k[:4])} 年 {int(k[5:])} 月" for k in keys]
        keys = stats.year_keys(start, end)
        return keys, [f"{k}" for k in keys], [f"{k} 年" for k in keys]

    def _refresh_income_chart(self, tasks, start, end):
        currencies = stats.currencies_used(tasks)
        choices = ([CONVERTED] if len(currencies) > 1 else []) + currencies
        if self.currency not in choices:
            self.currency = choices[0]
        self.currency_input.blockSignals(True)
        self.currency_input.clear()
        for cur in choices:
            self.currency_input.addItem(f"換算成 {self.base}" if cur == CONVERTED else cur, cur)
        self.currency_input.setCurrentIndex(max(0, self.currency_input.findData(self.currency)))
        self.currency_input.setVisible(len(choices) > 1)
        self.currency_input.blockSignals(False)

        if self.kind == "all":
            keys, labels, names = self._span_keys(start, end)
            every = "每月" if len(keys[0]) == 7 else "每年"
            highlight = None
        else:
            keys = [f"{self.year:04d}-{m:02d}" for m in range(1, 13)]
            labels = [f"{m}月" for m in range(1, 13)]
            names = [f"{self.year} 年 {m} 月" for m in range(1, 13)]
            every = f"{self.year} 年每月"
            highlight = self.month - 1 if self.kind == "month" else None
        if self.currency == CONVERTED:
            cur, approx = self.base, "≈ "
            values = stats.income_by_key(tasks, keys, cur, self.rates)
            missing = [c for c in currencies if currency_module.rate(c, cur, self.rates) is None]
            note = f"換算成 {cur}" + (f"，不含 {'、'.join(missing)}" if missing else "")
        else:
            cur, approx, note = self.currency, "", self.currency
            values = stats.income_by_key(tasks, keys, cur)
        self.income_title.setText(f"{every}收款（{note}）")
        self.income_chart.set_data(values, labels, highlight=highlight,
                                   tooltip_format=lambda i: f"{names[i]}收款：{approx}{money(cur, values[i])}")
        self.income_chart.empty_text = "還沒有收款紀錄" if self.kind == "all" else f"{self.year} 年還沒有收款紀錄"

    def _refresh_work_chart(self, records, work_days, start, end):
        hours = lambda s: f"{s / 3600:.1f}".rstrip("0").rstrip(".")
        if self.kind == "all":
            keys, labels, names = self._span_keys(start, end)
            values = stats.work_by_key(records, keys)
            self.work_title.setText("每月工時" if len(keys[0]) == 7 else "每年工時")
            self.work_chart.set_data(
                [v / 3600 for v in values], labels,
                axis_format=lambda v: f"{v:g}", value_format=lambda v: f"{v:.1f} 時",
                tooltip_format=lambda i: f"{names[i]}：{hours(values[i])} 小時")
        elif self.kind == "year":
            values = stats.work_by_month(records, self.year)
            self.work_title.setText(f"{self.year} 年每月工時")
            self.work_chart.set_data(
                [v / 3600 for v in values], [f"{m}月" for m in range(1, 13)],
                axis_format=lambda v: f"{v:g}", value_format=lambda v: f"{v:.1f} 時",
                tooltip_format=lambda i: f"{i + 1} 月：{hours(values[i])} 小時")
        else:
            self.work_title.setText(f"{self.month} 月每日工時")
            self.work_chart.set_data(
                [v / 3600 for _d, v in work_days], [str(int(d[8:])) for d, _v in work_days],
                axis_format=lambda v: f"{v:g}", value_format=lambda v: f"{v:.1f} 時",
                tooltip_format=lambda i: f"{work_days[i][0][5:].replace('-', '/')}：{hours(work_days[i][1])} 小時")
        self.work_chart.empty_text = "這段期間沒有打卡紀錄"

    def _refresh_clients(self, tasks, start, end):
        _clear(self.clients_list)
        rows = stats.client_rows(tasks, start, end)
        if not rows:
            self.clients_list.addWidget(label("這段期間沒有收款、交付或專注紀錄。", muted=True))
            return
        for r in rows:  # 長條用換算後的金額比較（沒有匯率的幣別不算）
            r["converted"] = currency_module.convert(r["paid"], self.base, self.rates)[0]
        rows.sort(key=lambda r: -r["converted"])
        peak = max((r["converted"] for r in rows), default=0) or 1
        for r in rows:
            row = _Row()
            v = QVBoxLayout(row)
            v.setContentsMargins(0, 10, 0, 10)
            v.setSpacing(4)
            top = QHBoxLayout()
            top.setSpacing(12)
            name = label(r["name"], wrap=True)
            name.setStyleSheet("font-weight: 700;")
            top.addWidget(name, 3)
            # 好幾種幣別的金額很長，要能換行，不然窄的時候會把整頁撐寬
            amount = label(self._money(r["paid"])[0] if r["paid"] else "—", wrap=True)
            amount.setStyleSheet("font-weight: 700;")
            amount.setAlignment(Qt.AlignRight | Qt.AlignTop)
            top.addWidget(amount, 2)
            v.addLayout(top)
            meta = [f"交付 {r['delivered']} 件" if r["delivered"] else "", f"專注 {_hours(r['focus'])}" if r["focus"] >= 60 else ""]
            if any(meta):
                v.addWidget(label(" · ".join(m for m in meta if m), muted=True, wrap=True))
            if r["converted"]:
                bar = QProgressBar()
                bar.setRange(0, 1000)
                bar.setValue(int(1000 * r["converted"] / peak))
                bar.setTextVisible(False)
                bar.setFixedHeight(6)
                bar.setToolTip(_amounts(r["paid"]).replace("\u200b", ""))
                v.addWidget(bar)
            self.clients_list.addWidget(row)

    def _refresh_tasks(self, tasks, start, end):
        _clear(self.tasks_list)
        if self.kind == "all":  # 全部：新的在前面，沒有日期的任務也列出來
            found = sorted(tasks, key=lambda t: f"{t.due_date} {t.due_time}", reverse=True)
        else:
            found = stats.period_tasks(tasks, start, end)
        rest = len(found) - self.task_limit
        self.more_btn.setVisible(rest > 0)
        self.more_btn.setText(f"再顯示 {min(rest, TASK_LIMIT)} 件（還有 {rest} 件）")
        if not found:
            self.tasks_list.addWidget(label("這段期間沒有交件、交付或收款的任務。", muted=True))
            return
        for t in found[:self.task_limit]:
            row = _Row(on_click=lambda tid=t.id: self.mw.open_task(tid))
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 10, 0, 10)
            h.setSpacing(12)
            col = QVBoxLayout()
            col.setSpacing(2)
            title = label(t.title, wrap=True)
            title.setStyleSheet("font-weight: 700;")
            col.addWidget(title)
            focus = tasks_service.focus_seconds(t)
            rate = tasks_service.hourly_rate(t)
            meta = [t.client, tasks_service.status_text(t),
                    f"專注 {tasks_service.focus_text(focus)}" if focus >= 60 else "",
                    f"時薪約 {money(t.currency or 'NTD', rate)}" if rate else ""]
            col.addWidget(label(" · ".join(m for m in meta if m), muted=True, wrap=True))
            h.addLayout(col, 1)
            amount = t.get_total_price()
            value = label(money(t.currency or "NTD", amount) if amount else "—")
            value.setStyleSheet("font-weight: 700;")
            h.addWidget(value, 0, Qt.AlignTop)
            self.tasks_list.addWidget(row)

    def _refresh_days(self, work_days):
        self.days_card.setVisible(self.kind == "month")
        if self.kind != "month":
            return
        _clear(self.days_list)
        records = self.data_manager.load_work_records()
        worked = [(d, v) for d, v in work_days if v > 0 or (d in records and records[d].sessions)]
        if not worked:
            self.days_list.addWidget(label("這個月沒有打卡紀錄。", muted=True))
            return
        for d, seconds in reversed(worked):
            day = date.fromisoformat(d)
            row = _Row(on_click=lambda ds=d: self.mw.edit_work_day(ds),
                       on_menu=lambda pos, ds=d: self._day_menu(ds, pos))
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 9, 0, 9)
            h.setSpacing(12)
            h.addWidget(label(f"{day.month}/{day.day}（{WEEKDAYS[day.weekday()]}）"), 1)
            h.addWidget(label(f"{len(records[d].sessions)} 段", muted=True))
            value = label(_hours(seconds), role="mono")
            value.setMinimumWidth(80)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(value)
            self.days_list.addWidget(row)

    def _day_menu(self, day, pos):
        menu = QMenu(self)
        menu.addAction("修改這天的打卡時間…", lambda: self.mw.edit_work_day(day))
        menu.addAction("刪除這天的打卡紀錄", lambda: self.mw.delete_work_day(day))
        menu.exec(pos)

    # --- 匯出 ---

    def export(self, everything: bool):
        tasks = self.data_manager.load_tasks()
        events = self.data_manager.load_events()
        records = self.data_manager.load_work_records()
        if everything or self.kind == "all":
            tables, name = stats.export_tables(tasks, events, records), "CocoTimer 全部資料"
        else:
            start, end = stats.period(self.kind, self.year, self.month)
            tables = stats.export_tables(tasks, events, records, start, end)
            name = f"CocoTimer 統計 {self.year}" + (f"-{self.month:02d}" if self.kind == "month" else "")
        path, chosen = QFileDialog.getSaveFileName(self, "匯出統計", name + ".xlsx",
                                                   "Excel 檔案 (*.xlsx);;CSV 檔案（每個表格一個檔案） (*.csv)")
        if not path:
            return
        try:
            if path.lower().endswith(".csv") or "csv" in chosen.lower():
                files = stats.write_csv_files(path, tables)
                QMessageBox.information(self, "匯出完成", "已匯出：\n" + "\n".join(files))
                return
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            try:
                stats.write_xlsx(path, tables)
            except ImportError:
                files = stats.write_csv_files(path[:-5], tables)
                QMessageBox.information(self, "匯出完成",
                                        "這台電腦沒有 Excel 匯出元件（openpyxl），已改存成 CSV（Excel 也打得開）：\n"
                                        + "\n".join(files))
                return
            QMessageBox.information(self, "匯出完成", f"已匯出：\n{path}")
        except OSError as e:
            QMessageBox.warning(self, "匯出失敗", f"無法寫入檔案：{e}")


class StatsWindow(QWidget):
    """在獨立視窗裡看統計（可以跟主視窗並排，側邊停靠收回時也還開著）。位置和大小會記住。"""
    DATA_FILES = ("tasks.json", "work_records.json")

    def __init__(self, main_window):
        super().__init__(None)
        self.mw = main_window
        self.setWindowTitle("統計 - CocoTimer")
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.page = StatsPage(main_window, self, popup=True)
        layout.addWidget(self.page)
        self.setMinimumSize(420, 480)
        self.resize(1000, 780)
        self._seen = None
        self.apply_theme()
        main_window.data_manager.restore_window_geometry("stats_window", self)

    def apply_theme(self):
        self.setStyleSheet(theme_module.stylesheet(self.mw.settings.theme))
        self.page.apply_colors()

    def refresh(self):
        self._seen = self.mw.data_manager.version(*self.DATA_FILES)
        self.page.refresh()

    def refresh_if_changed(self):
        """資料有變才重新整理（例如在主視窗改了任務後切回這個視窗）。"""
        if self.isVisible() and self.mw.data_manager.version(*self.DATA_FILES) != self._seen:
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.refresh_if_changed()


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
