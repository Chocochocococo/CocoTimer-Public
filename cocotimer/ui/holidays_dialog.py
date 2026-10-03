"""管理假日行事曆：匯入官方行事曆或各國假日、自訂休息日與補班日。"""
import copy
from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from cocotimer import holidays

WEEKDAYS = "一二三四五六日"

HELP_TEXT = (
    "・台灣：到「政府資料開放平臺」搜尋「行政機關辦公日曆表」，下載當年度 CSV 後匯入。\n"
    "・其他國家：在 Google 日曆加入該國的「國定假日」日曆，從設定匯出成 .ics 檔後匯入。\n"
    "・也可以用 Excel 做一份 CSV：第一欄日期、第二欄名稱，第三欄寫「補班」表示要上班的週末。"
)


class AddDaysDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增日期")
        form = QFormLayout(self)
        self.start = QDateEdit(QDate.currentDate())
        self.start.setCalendarPopup(True)
        self.end = QDateEdit(QDate.currentDate())
        self.end.setCalendarPopup(True)
        self.start.dateChanged.connect(lambda d: self.end.setDate(max(self.end.date(), d)))
        self.name = QLineEdit()
        self.name.setPlaceholderText("例如：春節、公司休假")
        self.kind = QComboBox()
        self.kind.addItem("放假", True)
        self.kind.addItem("補班（週末要上班）", False)
        form.addRow("開始日期:", self.start)
        form.addRow("結束日期:", self.end)
        form.addRow("名稱:", self.name)
        form.addRow("類型:", self.kind)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("新增")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def days(self):
        start, end = self.start.date().toPython(), self.end.date().toPython()
        off = self.kind.currentData()
        name = self.name.text().strip() or ("放假" if off else "補班")
        return {(start + timedelta(days=i)).isoformat(): {"name": name, "off": off}
                for i in range((end - start).days + 1)}


class HolidayCalendarsDialog(QDialog):
    def __init__(self, calendars, parent=None):
        super().__init__(parent)
        self.setWindowTitle("假日行事曆")
        self.setMinimumSize(820, 560)
        self.calendars = copy.deepcopy(calendars)

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(lambda _r: self._show())
        left.addWidget(self.list, 1)
        for text, slot in (("新增行事曆", self._add_calendar), ("重新命名", self._rename_calendar),
                           ("刪除行事曆", self._delete_calendar)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            left.addWidget(btn)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        self.info = QLabel()
        self.info.setWordWrap(True)
        right.addWidget(self.info)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("年份:"))
        self.year_filter = QComboBox()
        self.year_filter.currentIndexChanged.connect(lambda _i: self._fill_table())
        filter_row.addWidget(self.year_filter)
        filter_row.addStretch()
        right.addLayout(filter_row)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["日期", "星期", "名稱", "類型"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for col in (0, 1, 3):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right.addWidget(self.table, 1)
        actions = QHBoxLayout()
        for text, slot in (("匯入檔案…", self._import), ("新增日期…", self._add_days), ("刪除選取", self._delete_days)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            actions.addWidget(btn)
        actions.addStretch()
        right.addLayout(actions)
        help_label = QLabel(HELP_TEXT)
        help_label.setWordWrap(True)
        help_label.setProperty("muted", True)
        right.addWidget(help_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("確定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        root.addLayout(right, 3)

        self._refresh_list()

    # --- 行事曆清單 ---

    def _current(self):
        row = self.list.currentRow()
        return self.calendars[row] if 0 <= row < len(self.calendars) else None

    def _refresh_list(self, select=0):
        self.list.blockSignals(True)
        self.list.clear()
        for c in self.calendars:
            self.list.addItem(c.get("name", ""))
        self.list.blockSignals(False)
        if self.calendars:
            self.list.setCurrentRow(min(select, len(self.calendars) - 1))
        self._show()

    def _add_calendar(self):
        name, ok = QInputDialog.getText(self, "新增行事曆", "名稱（例如：日本國定假日、公司休假）:")
        if ok and name.strip():
            self.calendars.append(holidays.new_calendar(name.strip()))
            self._refresh_list(len(self.calendars) - 1)

    def _rename_calendar(self):
        calendar = self._current()
        if calendar is None:
            return
        name, ok = QInputDialog.getText(self, "重新命名", "名稱:", text=calendar.get("name", ""))
        if ok and name.strip():
            calendar["name"] = name.strip()
            self._refresh_list(self.list.currentRow())

    def _delete_calendar(self):
        calendar = self._current()
        if calendar is None:
            return
        if QMessageBox.question(self, "刪除行事曆", f"確定要刪除「{calendar.get('name', '')}」嗎？") == QMessageBox.Yes:
            row = self.list.currentRow()
            self.calendars.pop(row)
            self._refresh_list(row)

    # --- 日期 ---

    def _show(self):
        calendar = self._current()
        self.year_filter.blockSignals(True)
        self.year_filter.clear()
        if calendar is None:
            self.info.setText("還沒有行事曆。")
            self.year_filter.blockSignals(False)
            self._fill_table()
            return
        years = holidays.years(calendar)
        self.year_filter.addItem("全部", None)
        for y in years:
            self.year_filter.addItem(str(y), y)
        this_year = self.year_filter.findData(date.today().year)
        self.year_filter.setCurrentIndex(this_year if this_year >= 0 else 0)
        self.year_filter.blockSignals(False)
        covered = "、".join(map(str, years)) if years else "還沒有資料"
        note = calendar.get("note", "")
        self.info.setText(f"<b>{calendar.get('name', '')}</b>　已有資料的年份：{covered}"
                          + (f"<br><span style='color:#888'>{note}</span>" if note else ""))
        self._fill_table()

    def _fill_table(self):
        calendar = self._current()
        year = self.year_filter.currentData()
        self.table.setRowCount(0)
        if calendar is None:
            return
        for key in sorted(calendar.get("days", {})):
            if year is not None and not key.startswith(f"{year}-"):
                continue
            entry = calendar["days"][key]
            row = self.table.rowCount()
            self.table.insertRow(row)
            d = date.fromisoformat(key)
            date_item = QTableWidgetItem(key)
            date_item.setData(Qt.UserRole, key)
            self.table.setItem(row, 0, date_item)
            self.table.setItem(row, 1, QTableWidgetItem(WEEKDAYS[d.weekday()]))
            self.table.setItem(row, 2, QTableWidgetItem(entry.get("name", "")))
            self.table.setItem(row, 3, QTableWidgetItem("放假" if entry.get("off") else "補班"))

    def _import(self):
        calendar = self._current()
        if calendar is None:
            QMessageBox.information(self, "提示", "請先新增或選擇一個行事曆。")
            return
        path, _ = QFileDialog.getOpenFileName(self, "匯入假日", "", "假日檔案 (*.csv *.ics *.json *.txt);;所有檔案 (*)")
        if not path:
            return
        try:
            days, kind = holidays.parse_file(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "無法匯入", f"讀取檔案失敗：{e}")
            return
        if not days:
            QMessageBox.warning(self, "無法匯入", "檔案裡沒有找到任何日期。")
            return
        added, updated = holidays.merge(calendar, days)
        self._show()
        QMessageBox.information(self, "匯入完成", f"格式：{kind}\n新增 {added} 天，更新 {updated} 天。")

    def _add_days(self):
        calendar = self._current()
        if calendar is None:
            QMessageBox.information(self, "提示", "請先新增或選擇一個行事曆。")
            return
        dialog = AddDaysDialog(self)
        if dialog.exec() == QDialog.Accepted:
            holidays.merge(calendar, dialog.days())
            self._show()

    def _delete_days(self):
        calendar = self._current()
        if calendar is None:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        for row in rows:
            calendar["days"].pop(self.table.item(row, 0).data(Qt.UserRole), None)
        if rows:
            self._show()

    def result_calendars(self):
        return self.calendars
