"""任務列表：篩選（進行中／待收款／已結案／全部）、搜尋、排序，右鍵可以快速改狀態。"""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QBoxLayout, QComboBox, QDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from cocotimer import tasks as tasks_service
from cocotimer.ui.batch_dialog import BatchStatusDialog
from cocotimer.ui.icons import icon
from cocotimer.ui.task_dialog import TaskEditDialog
from cocotimer.ui.today_page import DUE_CHIP, money, money_lines
from cocotimer.ui.widgets import SegmentBar, button, label

WEEKDAYS = "一二三四五六日"
COLUMNS = ["任務", "交件／收款", "數量（委託 → 計費）", "金額", "狀態", "進度"]
NARROW = 820  # 比這個窄時隱藏「數量」與「進度」欄
COMPACT = 560  # 比這個窄（例如側邊停靠）時只留「任務」和「狀態」兩欄，日期與金額併到任務欄


def _cell(*widgets, spacing=2):
    holder = QWidget()
    holder.setProperty("cell", True)
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(spacing)
    for w in widgets:
        layout.addWidget(w)
    return holder


def _date_text(iso: str, time: str = "") -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.month:02d}/{d.day:02d}（{WEEKDAYS[d.weekday()]}）{(' ' + time) if time else ''}"


class TaskPage(QWidget):
    """工作任務管理頁面（v3）。對外介面和舊版相同：tasks、update_task_list、open_add_task_dialog、_update_task。"""

    def __init__(self, data_manager, main_window=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.main_window = main_window
        self.tasks = self.data_manager.load_tasks()
        self.max_completed_tasks = self.data_manager.load_settings().max_completed_tasks
        self.group = "active"
        self.sort = "due"
        self.shown = []
        self.compact = False
        self._build_ui()
        self.update_task_list()

    # --- 版面 ---

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)

        self.header = QBoxLayout(QBoxLayout.LeftToRight)
        self.header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("任務")
        title.setObjectName("pageTitle")
        self.summary = label("", muted=True, wrap=True)
        titles.addWidget(title)
        titles.addWidget(self.summary)
        self.header.addLayout(titles, 1)
        actions = QBoxLayout(QBoxLayout.LeftToRight)
        actions.setSpacing(8)
        self.actions = actions
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋任務、專案、客戶或備註")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(220)
        self.search.textChanged.connect(lambda _t: self.update_task_list())
        add_btn = button("新增任務", primary=True)
        add_btn.clicked.connect(self.open_add_task_dialog)
        batch_btn = button("批次改狀態")
        batch_btn.setToolTip("依狀態、客戶或期間找出任務，一次改成已交付、已請款或已收款")
        batch_btn.clicked.connect(self.open_batch_dialog)
        actions.addWidget(self.search, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(batch_btn, 1)
        buttons.addWidget(add_btn, 1)
        actions.addLayout(buttons)
        self.header.addLayout(actions)
        root.addLayout(self.header)

        bar = QBoxLayout(QBoxLayout.LeftToRight)
        self.filter_bar = bar
        self.filters = SegmentBar(tasks_service.FILTERS)
        self.filters.set_current(self.group)
        self.filters.changed.connect(self._set_group)
        bar.addWidget(self.filters)
        sort_row = QHBoxLayout()
        sort_row.addStretch()
        sort_row.addWidget(label("排序", muted=True))
        self.sort_input = QComboBox()
        for key, text in tasks_service.SORTS:
            self.sort_input.addItem(text, key)
        self.sort_input.currentIndexChanged.connect(self._set_sort)
        sort_row.addWidget(self.sort_input)
        bar.addLayout(sort_row, 1)
        root.addLayout(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("taskTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_menu)
        self.table.cellDoubleClicked.connect(lambda row, _col: self._edit_row(row))
        QShortcut(QKeySequence.Delete, self.table, activated=self._delete_selected)
        QShortcut(QKeySequence(Qt.Key_Return), self.table, activated=lambda: self._edit_row(self.table.currentRow()))
        root.addWidget(self.table, 1)

        footer = QBoxLayout(QBoxLayout.LeftToRight)
        self.footer = footer
        self.hint = label("", muted=True, wrap=True)
        self.totals = label("", wrap=True)
        self.totals.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.totals.setStyleSheet("font-weight: 700;")
        footer.addWidget(self.hint, 1)
        total_row = QHBoxLayout()
        total_row.addStretch()
        total_row.addWidget(label("目前篩選合計", muted=True))
        total_row.addWidget(self.totals, 1)
        footer.addLayout(total_row)
        root.addLayout(footer)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()
        narrow = width < NARROW
        compact = width < COMPACT
        stacked = QBoxLayout.TopToBottom if width < 640 else QBoxLayout.LeftToRight
        self.layout().setContentsMargins(*((16, 20, 16, 16) if compact else (28, 24, 28, 20)))
        self.header.setDirection(stacked)
        self.actions.setDirection(QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)
        self.search.setMinimumWidth(0 if compact else 220)
        # 分段按鈕（含件數）和排序放不進同一列時就上下排，不要把按鈕擠扁
        need = self.filters.sizeHint().width() + self.sort_input.sizeHint().width() + 80
        if self.filters.property("compact"):  # 縮小留白時每顆按鈕左右少了 8 px
            need += 16 * len(self.filters.buttons)
        side = 32 if compact else 56
        self.filter_bar.setDirection(QBoxLayout.TopToBottom if width < 640 or width - side < need
                                     else QBoxLayout.LeftToRight)
        self.footer.setDirection(stacked)
        self.filters.set_compact(self.filter_bar.direction() == QBoxLayout.TopToBottom)  # 和其他列上下排時，分段按鈕平均撐滿寬度
        for col in (2, 5):
            self.table.setColumnHidden(col, narrow)
        for col in (1, 3):
            self.table.setColumnHidden(col, compact)
        if compact != self.compact:
            self.compact = compact
            self.update_task_list()

    # --- 資料 ---

    def _set_group(self, group):
        self.group = group
        self.update_task_list()

    def _set_sort(self, _index):
        self.sort = self.sort_input.currentData()
        self.update_task_list()

    def update_task_list(self):
        counts = tasks_service.group_counts(self.tasks)
        self.filters.set_counts({} if self.compact else counts)  # 窄的時候放不下數字（上方摘要已經有）
        overdue = sum(1 for t in self.tasks if t.status == tasks_service.IN_PROGRESS
                      and tasks_service.due_info(t)[1] == "overdue")
        late = sum(1 for t in self.tasks if tasks_service.payment_info(t)[1] == "late")
        parts = [f"{counts['active']} 件進行中"]
        if overdue:
            parts.append(f"{overdue} 件逾期")
        parts.append(f"{counts['receivable']} 件待收款")
        if late:
            parts.append(f"{late} 件超過預計收款日")
        self.summary.setText(" · ".join(parts))

        limit = self.max_completed_tasks if self.group in ("closed", "all") else None
        self.shown, hidden = tasks_service.task_list(self.tasks, self.group, self.search.text(), self.sort, limit)
        self.hint.setText(f"另有 {hidden} 件較早的已結案任務沒有顯示（可在「設定」調整顯示筆數）" if hidden else
                          ("沒有符合的任務。" if not self.shown else "雙擊編輯，右鍵可以快速改狀態。"))
        # 「、」後面可以換行，好幾種幣別時窄的視窗也放得下
        self.totals.setText(money_lines(tasks_service.totals_by_currency(self.shown)).replace("、", "、\u200b"))

        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(self.shown))
        for row, task in enumerate(self.shown):
            self._fill_row(row, task)
        self.table.resizeRowsToContents()
        self.table.setUpdatesEnabled(True)

    def _fill_row(self, row, task):
        anchor = QTableWidgetItem()
        anchor.setData(Qt.UserRole, task.id)
        self.table.setItem(row, 0, anchor)

        title = label(task.title)
        title.setStyleSheet("font-weight: 700;")
        meta = " · ".join(p for p in (task.client, task.project_name) if p)
        lines = [title, label(meta, muted=True, wrap=self.compact)]
        if self.compact:
            # 窄版：交件日與金額併到任務欄
            amount = task.get_total_price()
            when = _date_text(task.due_date, task.due_time)
            lines.append(label(" · ".join(p for p in (when, money(task.currency or "NTD", amount) if amount else "") if p),
                               role="mono", muted=True))
            title.setWordWrap(True)
        holder = _cell(*lines)
        holder.setToolTip(f"{task.title}\n{meta}" + (f"\n\n{task.description}" if task.description else ""))
        self.table.setCellWidget(row, 0, holder)

        due_kind = tasks_service.due_info(task)
        pay_text, pay_kind = tasks_service.payment_info(task)
        if task.status == tasks_service.IN_PROGRESS:
            note, kind = due_kind
            colors = {"overdue": "danger", "today": "warn"}
        else:
            note, kind = pay_text or tasks_service.status_text(task), pay_kind
            colors = {"late": "danger"}
        when = label(_date_text(task.due_date, task.due_time), role="mono")
        note_label = label(note, muted=kind not in colors)
        if kind in colors:
            note_label.setProperty("tone", colors[kind])
        self.table.setCellWidget(row, 1, _cell(when, note_label))

        self.table.setCellWidget(row, 2, _cell(label(tasks_service.billing_summary(task) or "—")))

        amount = task.get_total_price()
        amount_label = label(money(task.currency or "NTD", amount) if amount else "—")
        amount_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        amount_label.setStyleSheet("font-weight: 700;")
        self.table.setCellWidget(row, 3, _cell(amount_label))

        if task.status == tasks_service.IN_PROGRESS:
            chip_kind, chip_text = DUE_CHIP.get(due_kind[1], ("blue", "進行中"))
        else:
            chip_kind, chip_text = tasks_service.STATUS_CHIPS[task.status], tasks_service.status_text(task)
            if pay_kind == "late":
                chip_kind = "red"
        chip = label(chip_text, chip=chip_kind)
        holder = _cell(chip)
        holder.layout().setAlignment(chip, Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setCellWidget(row, 4, holder)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(task.completion)
        bar.setTextVisible(False)
        bar.setFixedWidth(90)
        if due_kind[1] == "overdue":
            bar.setProperty("danger", True)
        pct = label(f"{task.completion}%", role="mono", muted=True)
        progress = QWidget()
        progress.setProperty("cell", True)
        h = QHBoxLayout(progress)
        h.setContentsMargins(10, 8, 14, 8)
        h.addWidget(bar)
        h.addWidget(pct)
        self.table.setCellWidget(row, 5, progress)

    def _task_at(self, row):
        item = self.table.item(row, 0)
        return self._find_task_by_id(item.data(Qt.UserRole)) if item else None

    def _find_task_by_id(self, task_id):
        return next((t for t in self.tasks if t.id == task_id), None)

    # --- 新增／編輯／刪除 ---

    def _changed(self):
        self.update_task_list()
        if self.main_window and hasattr(self.main_window, "refresh_tasks"):
            self.main_window.refresh_tasks()

    def open_add_task_dialog(self):
        dialog = TaskEditDialog(self.data_manager, parent=self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_task_data()
            if data:
                tasks_service.save_task_edit(self.data_manager, self.tasks, None, data)
                self._changed()

    def edit_task(self, task):
        dialog = TaskEditDialog(self.data_manager, task=task, parent=self, on_delete=self.delete_task)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_task_data()
            if data:
                self._update_task(task, data)

    def _edit_row(self, row):
        task = self._task_at(row)
        if task:
            self.edit_task(task)

    def _update_task(self, task, task_data):
        tasks_service.save_task_edit(self.data_manager, self.tasks, task, task_data)
        self._changed()

    def delete_task(self, task, confirm=True) -> bool:
        if confirm and QMessageBox.question(self, "刪除任務", f"確定要刪除「{task.title}」嗎？\n刪除後無法復原（但每日備份裡還找得到）。") != QMessageBox.Yes:
            return False
        self.tasks = [t for t in self.tasks if t.id != task.id]
        self.data_manager.save_tasks(self.tasks)
        self._changed()
        return True

    def _delete_selected(self):
        task = self._task_at(self.table.currentRow())
        if task:
            self.delete_task(task)

    def _set_status(self, task, status):
        if status == tasks_service.IN_PROGRESS:
            tasks_service.update_completion(task, min(task.completion, 90))
        else:
            tasks_service.set_status(task, status)
        self.data_manager.save_tasks(self.tasks)
        self._changed()

    def open_batch_dialog(self):
        self.tasks = self.data_manager.load_tasks()
        dialog = BatchStatusDialog(self.data_manager, self.tasks, self)
        if dialog.exec() != QDialog.Accepted or not dialog.before:
            return
        self.data_manager.save_tasks(self.tasks)
        self._changed()
        target = tasks_service.STATUS_LABELS[dialog.target]
        box = QMessageBox(self)
        box.setWindowTitle("批次修改狀態")
        box.setIcon(QMessageBox.Information)
        box.setText(f"已將 {len(dialog.before)} 件任務改成「{target}」。")
        box.addButton("好", QMessageBox.AcceptRole)
        undo = box.addButton("復原", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is undo:
            tasks_service.restore_tasks(self.tasks, dialog.before)
            self.data_manager.save_tasks(self.tasks)
            self._changed()

    def _show_menu(self, pos):
        row = self.table.rowAt(pos.y())
        task = self._task_at(row)
        if task is None:
            return
        self.table.selectRow(row)
        menu = QMenu(self)
        menu.addAction("編輯…", lambda: self.edit_task(task))
        menu.addSeparator()
        for key, text in tasks_service.STATUSES:
            action = menu.addAction(f"標記為「{text}」", lambda k=key: self._set_status(task, k))
            action.setCheckable(True)
            action.setChecked(task.status == key)
        menu.addAction("批次修改狀態…", self.open_batch_dialog)
        menu.addSeparator()
        danger = self.main_window.colors["danger"] if self.main_window else "#9E2219"
        menu.addAction(icon("close", danger, 16), "刪除", lambda: self.delete_task(task))
        menu.exec(self.table.viewport().mapToGlobal(pos))
