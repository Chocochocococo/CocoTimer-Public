"""批次修改任務狀態：用狀態、客戶、期間找出任務，確認清單後一次修改（例如把舊資料一次標成已收款）。"""
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox, QScrollArea, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from cocotimer import tasks as tasks_service
from cocotimer.ui.today_page import money, money_lines
from cocotimer.ui.widgets import SegmentBar, button, card, label

COLUMNS = ["任務", "客戶", "交件日", "預計收款日", "目前狀態", "金額"]


def _short(iso):
    return iso.replace("-", "/") if iso else "—"


def _date_edit(qdate):
    edit = QDateEdit(qdate)
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("yyyy/MM/dd")
    return edit


class BatchStatusDialog(QDialog):
    """tasks 是任務頁目前的任務清單；按「套用」後會直接修改這些任務物件（不會自己存檔），
    修改前的資料放在 self.before，可以交給 tasks.restore_tasks 復原。"""

    def __init__(self, data_manager, tasks, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.tasks = tasks
        self.clients = data_manager.load_clients()
        self.matched = []
        self.excluded = set()  # 使用者在清單裡取消勾選的任務
        self.before = {}
        self.applied = []
        self.target = tasks_service.PAID
        self.setWindowTitle("批次修改狀態")
        self.setMinimumSize(640, 600)
        self._build_ui()
        self.data_manager.restore_window_geometry("batch_status_dialog", self)
        if self.width() < 640 or self.height() < 600:
            self.resize(900, 900)
        self._refresh()

    # --- 版面 ---

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("contentArea")
        scroll.setWidget(content)
        body = QVBoxLayout(content)
        body.setContentsMargins(24, 20, 24, 16)
        body.setSpacing(14)
        title = QLabel("批次修改狀態")
        title.setObjectName("pageTitle")
        body.addWidget(title)
        body.addWidget(label("先設定條件找出任務，確認清單後再一次修改。改完可以馬上復原。", muted=True, wrap=True))

        body.addWidget(self._build_filter_card())
        body.addWidget(self._build_target_card())
        body.addWidget(self._build_list_card(), 1)
        layout.addWidget(scroll, 1)

        footer = QFrame()
        footer.setProperty("card", True)
        footer.setStyleSheet("QFrame { border-radius: 0; border-left: none; border-right: none; border-bottom: none; }")
        row = QHBoxLayout(footer)
        row.setContentsMargins(20, 12, 20, 12)
        row.addStretch()
        cancel = button("取消")
        cancel.setMinimumWidth(96)
        cancel.clicked.connect(self.reject)
        self.apply_btn = button("套用", primary=True)
        self.apply_btn.setMinimumWidth(150)
        self.apply_btn.clicked.connect(self._apply)
        row.addWidget(cancel)
        row.addWidget(self.apply_btn)
        layout.addWidget(footer)

    def _build_filter_card(self):
        c = card(spacing=10)
        c.layout().addWidget(label("1. 找出這些任務", role="h2"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        grid.addWidget(label("目前狀態", muted=True), 0, 0)
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self.status_buttons = {}
        for key, text in tasks_service.STATUSES:
            btn = button(text, pill=True, checkable=True)
            btn.setChecked(key in (tasks_service.DELIVERED, tasks_service.INVOICED))
            btn.toggled.connect(lambda _on: self._refresh())
            status_row.addWidget(btn)
            self.status_buttons[key] = btn
        status_row.addStretch()
        grid.addLayout(status_row, 0, 1)

        grid.addWidget(label("客戶", muted=True), 1, 0)
        self.client_input = QComboBox()
        self.client_input.addItem("全部客戶", None)
        self.client_input.addItem("（沒有指定客戶）", tasks_service.NO_CLIENT)
        for client in sorted(self.clients, key=lambda c: (c.archived, c.name)):
            self.client_input.addItem(client.name + ("（已封存）" if client.archived else ""), client.id)
        self.client_input.currentIndexChanged.connect(lambda _i: self._refresh())
        grid.addWidget(self.client_input, 1, 1)

        grid.addWidget(label("期間", muted=True), 2, 0)
        period = QHBoxLayout()
        period.setSpacing(8)
        dates = QHBoxLayout()
        dates.setSpacing(8)
        self.period_check = QCheckBox("限定")
        self.period_check.toggled.connect(self._period_toggled)
        self.date_field = QComboBox()
        for key, text in tasks_service.BATCH_DATE_FIELDS:
            self.date_field.addItem(text, key)
        today = QDate.currentDate()
        self.start_input = _date_edit(QDate(today.year() - 1, 1, 1))
        self.end_input = _date_edit(today)
        for w in (self.date_field, self.start_input, self.end_input):
            w.setEnabled(False)
        self.date_field.currentIndexChanged.connect(lambda _i: self._refresh())
        self.start_input.dateChanged.connect(lambda _d: self._refresh())
        self.end_input.dateChanged.connect(lambda _d: self._refresh())
        period.addWidget(self.period_check)
        period.addWidget(self.date_field)
        period.addWidget(label("在這段期間內", muted=True))
        period.addStretch()
        dates.addWidget(self.start_input, 1)
        dates.addWidget(label("～"))
        dates.addWidget(self.end_input, 1)
        grid.addLayout(period, 2, 1)
        grid.addLayout(dates, 3, 1)
        c.layout().addLayout(grid)
        return c

    def _build_target_card(self):
        c = card(spacing=10)
        c.layout().addWidget(label("2. 改成", role="h2"))
        row = QHBoxLayout()
        row.setSpacing(12)
        self.target_bar = SegmentBar(tasks_service.STATUSES)
        self.target_bar.set_current(self.target)
        self.target_bar.changed.connect(self._set_target)
        row.addWidget(self.target_bar)
        row.addStretch()
        c.layout().addLayout(row)
        dates = QHBoxLayout()
        dates.setContentsMargins(0, 0, 0, 0)
        dates.setSpacing(8)
        self.date_label = label("", muted=True)
        dates.addWidget(self.date_label)
        self.date_mode = QComboBox()
        for key, text in tasks_service.BATCH_DATE_MODES:
            self.date_mode.addItem(text, key)
        self.date_mode.currentIndexChanged.connect(self._date_mode_changed)
        self.fixed_date = _date_edit(QDate.currentDate())
        self.fixed_date.setEnabled(False)
        dates.addWidget(self.date_mode, 1)
        dates.addWidget(self.fixed_date)
        self.date_row = QWidget()
        self.date_row.setLayout(dates)
        c.layout().addWidget(self.date_row)
        self.date_hint = label("", muted=True, wrap=True)
        c.layout().addWidget(self.date_hint)
        self._update_date_hint()
        return c

    def _build_list_card(self):
        c = card(spacing=8)
        head = QHBoxLayout()
        head.addWidget(label("3. 確認清單", role="h2"))
        head.addStretch()
        select_all = button("全選", link=True)
        select_all.clicked.connect(lambda: self._check_all(True))
        select_none = button("全不選", link=True)
        select_none.clicked.connect(lambda: self._check_all(False))
        head.addWidget(select_all)
        head.addWidget(select_none)
        c.layout().addLayout(head)
        self.count_label = label("", wrap=True)
        c.layout().addWidget(self.count_label)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("taskTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setMinimumHeight(240)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellClicked.connect(self._cell_clicked)
        c.layout().addWidget(self.table, 1)
        return c

    def resizeEvent(self, event):
        super().resizeEvent(event)
        narrow = self.width() < 760
        for col in (1, 3):
            self.table.setColumnHidden(col, narrow)

    # --- 條件 ---

    def _period_toggled(self, on):
        for w in (self.date_field, self.start_input, self.end_input):
            w.setEnabled(on)
        self._refresh()

    def _set_target(self, key):
        self.target = key
        self._update_date_hint()
        self._refresh()

    def _date_mode_changed(self, _index):
        self.fixed_date.setEnabled(self.date_mode.currentData() == "fixed")
        self._update_date_hint()

    def _update_date_hint(self):
        target = self.target
        self.date_row.setVisible(target != tasks_service.IN_PROGRESS)
        names = {tasks_service.DELIVERED: "交付日", tasks_service.INVOICED: "請款日", tasks_service.PAID: "收款日"}
        self.date_label.setText(f"{names.get(target, '')}填入")
        if target == tasks_service.IN_PROGRESS:
            text = "改回進行中時，交付、請款、收款日期都會清掉，完成度改成最多 90%。"
        elif self.date_mode.currentData() == "expected":
            text = "交付日用交件日、請款日用結算日、收款日用預計收款日；還沒到的日子就用今天。已經填好的日期會保留。"
        else:
            text = "沒填過的日期都填同一天，已經填好的日期會保留。"
        self.date_hint.setText(text)

    def _criteria(self):
        statuses = {k for k, b in self.status_buttons.items() if b.isChecked()}
        client = self.client_input.currentData()
        start = end = ""
        if self.period_check.isChecked():
            start = self.start_input.date().toString("yyyy-MM-dd")
            end = self.end_input.date().toString("yyyy-MM-dd")
        return dict(statuses=statuses, client_ids=None if client is None else {client},
                    date_field=self.date_field.currentData(), start=start, end=end)

    # --- 清單 ---

    def _refresh(self):
        if not hasattr(self, "table"):
            return
        self.matched = tasks_service.batch_matches(self.tasks, **self._criteria())
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.matched))
        for row, t in enumerate(self.matched):
            title = QTableWidgetItem(t.title + (f"  ·  {t.project_name}" if t.project_name else ""))
            title.setData(Qt.UserRole, t.id)
            title.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            title.setCheckState(Qt.Unchecked if t.id in self.excluded else Qt.Checked)
            title.setToolTip(title.text())
            pay_text, pay_kind = tasks_service.payment_info(t)
            status = QTableWidgetItem(tasks_service.status_text(t) + ("（逾期）" if pay_kind == "late" else ""))
            amount = t.get_total_price()
            amount_item = QTableWidgetItem(money(t.currency or "NTD", amount) if amount else "—")
            amount_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            cells = [title, QTableWidgetItem(t.client or "—"), QTableWidgetItem(_short(t.due_date)),
                     QTableWidgetItem(_short(t.payment_date)), status, amount_item]
            for col, item in enumerate(cells):
                if col:
                    item.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        self.table.resizeRowsToContents()
        self._update_count()

    def _chosen(self):
        return [t for t in self.matched if t.id not in self.excluded]

    def _update_count(self):
        chosen = self._chosen()
        target = tasks_service.STATUS_LABELS[self.target]
        if not self.matched:
            self.count_label.setText("沒有符合條件的任務。")
        else:
            totals = tasks_service.totals_by_currency(chosen)
            skipped = len(self.matched) - len(chosen)
            self.count_label.setText(f"符合 {len(self.matched)} 件，已勾選 {len(chosen)} 件"
                                     + (f"（{skipped} 件不改）" if skipped else "")
                                     + (f" · 合計 {money_lines(totals)}" if totals else ""))
        already = sum(1 for t in chosen if t.status == self.target)
        self.apply_btn.setText(f"改成「{target}」（{len(chosen)} 件）")
        self.apply_btn.setEnabled(len(chosen) > already)

    def _item_changed(self, item):
        if item.column() != 0:
            return
        task_id = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self.excluded.discard(task_id)
        else:
            self.excluded.add(task_id)
        self._update_count()

    def _cell_clicked(self, row, col):
        if col == 0:
            return  # 勾選框本身會處理
        item = self.table.item(row, 0)
        if item:
            item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _check_all(self, on):
        ids = {t.id for t in self.matched}
        self.excluded = self.excluded - ids if on else self.excluded | ids
        self._refresh()

    # --- 套用 ---

    def _apply(self):
        chosen = [t for t in self._chosen() if t.status != self.target]
        if not chosen:
            return
        target = tasks_service.STATUS_LABELS[self.target]
        if QMessageBox.question(self, "批次修改狀態", f"要把 {len(chosen)} 件任務改成「{target}」嗎？\n改完之後可以按「復原」還原。",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        fixed = self.fixed_date.date().toString("yyyy-MM-dd")
        self.before = tasks_service.apply_batch_status(chosen, self.target, self.date_mode.currentData(), fixed,
                                                       date.today().isoformat())
        self.applied = chosen
        self.accept()
