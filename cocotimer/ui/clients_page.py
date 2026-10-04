"""「客戶」分頁：客戶資料、單價範本、加權表、結算與收款規則。"""
import copy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QBoxLayout, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from cocotimer import billing
from cocotimer import tasks as tasks_service
from cocotimer.models import Client
from cocotimer.ui.billing_widgets import PaymentRuleEditor, number_box
from cocotimer.ui.holidays_dialog import HolidayCalendarsDialog
from cocotimer.ui.task_dialog import CURRENCIES
from cocotimer.ui.widgets import button, card, label

GENERAL = "__general__"


def _shrinkable(combo: QComboBox, chars: int = 6):
    """下拉選單預設會撐到最長選項的寬度，窄版面時改成可以縮小（選項文字會截斷）。"""
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)


def _money(amounts: dict) -> str:
    return "、".join(f"{cur} {amt:,.0f}" for cur, amt in sorted(amounts.items())) or "0"


class RatesTable(QTableWidget):
    """單價範本表格：項目、單位、單價、預設計費方式。"""

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setHorizontalHeaderLabels(["項目", "單位", "單價", "預設計費方式"])
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._ids = []

    def set_compact(self, compact: bool):
        """窄的時候「項目」欄不再自動撐滿（否則會被擠到看不見），改成固定寬度並允許左右捲動。"""
        header = self.horizontalHeader()
        if compact:
            header.setSectionResizeMode(0, QHeaderView.Interactive)
            header.resizeSection(0, 130)
        else:
            header.setSectionResizeMode(0, QHeaderView.Stretch)

    def load(self, rates):
        self.setRowCount(0)
        self._ids = []
        for rate in rates:
            self.add_rate(rate)

    def add_rate(self, rate=None):
        rate = rate or billing.new_rate()
        row = self.rowCount()
        self.insertRow(row)
        self._ids.append(rate.get("id") or billing.new_id())
        self.setItem(row, 0, QTableWidgetItem(rate.get("name", "")))
        unit = QComboBox()
        unit.setEditable(True)
        unit.addItems(billing.UNITS)
        unit.setCurrentText(rate.get("unit", ""))
        self.setCellWidget(row, 1, unit)
        price = number_box(decimals=3)
        price.setValue(float(rate.get("unit_price", 0) or 0))
        self.setCellWidget(row, 2, price)
        mode = QComboBox()
        for key, text in billing.BILLING_MODES:
            mode.addItem(text, key)
        mode.setCurrentIndex(max(0, mode.findData(rate.get("billing", billing.SIMPLE))))
        self.setCellWidget(row, 3, mode)
        if not rate.get("name"):
            self.editItem(self.item(row, 0))

    def remove_selected(self):
        for row in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(row)
            del self._ids[row]

    def unnamed_row(self):
        """第一個「沒有名稱但有填單價」的列（沒有就回傳 None）。"""
        for row in range(self.rowCount()):
            name = (self.item(row, 0).text() if self.item(row, 0) else "").strip()
            if not name and self.cellWidget(row, 2).value() != 0:
                return row
        return None

    def rates(self):
        result = []
        for row in range(self.rowCount()):
            name = (self.item(row, 0).text() if self.item(row, 0) else "").strip()
            if not name:
                continue
            result.append({"id": self._ids[row], "name": name,
                           "unit": self.cellWidget(row, 1).currentText().strip(),
                           "unit_price": self.cellWidget(row, 2).value(),
                           "billing": self.cellWidget(row, 3).currentData()})
        return result


class WeightingProfilesDialog(QDialog):
    """管理加權表：名稱、是否取整數、各級距與計費比例。"""

    def __init__(self, profiles, default_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理加權表")
        self.setMinimumSize(720, 460)
        self.profiles = copy.deepcopy(profiles)
        self.default_id = default_id
        self._current = -1

        layout = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        for text, slot in (("新增加權表", self._add), ("刪除", self._delete), ("設為預設", self._make_default)):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            left.addWidget(btn)
        layout.addLayout(left, 1)

        right = QVBoxLayout()
        form = QFormLayout()
        self.name_input = QLineEdit()
        form.addRow("名稱:", self.name_input)
        self.round_input = QCheckBox("計費數量四捨五入到整數")
        form.addRow("", self.round_input)
        right.addLayout(form)
        self.bands = QTableWidget(0, 2)
        self.bands.setHorizontalHeaderLabels(["級距", "計費比例 (%)"])
        self.bands.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.bands.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.bands.verticalHeader().setVisible(False)
        right.addWidget(self.bands, 1)
        band_buttons = QHBoxLayout()
        add_band = QPushButton("新增級距")
        add_band.clicked.connect(lambda: self._add_band("", 1.0))
        remove_band = QPushButton("刪除選取級距")
        remove_band.clicked.connect(self._remove_band)
        band_buttons.addWidget(add_band)
        band_buttons.addWidget(remove_band)
        band_buttons.addStretch()
        right.addLayout(band_buttons)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("確定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        layout.addLayout(right, 2)

        self._refresh_list()
        self.list.setCurrentRow(0)

    def _refresh_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.profiles:
            mark = "（預設）" if p.get("id") == self.default_id else ""
            self.list.addItem(f"{p.get('name', '')}{mark}")
        self.list.blockSignals(False)

    def _store_current(self):
        if 0 <= self._current < len(self.profiles):
            p = self.profiles[self._current]
            p["name"] = self.name_input.text().strip() or "未命名加權表"
            p["round_to_integer"] = self.round_input.isChecked()
            p["bands"] = [{"label": (self.bands.item(r, 0).text() if self.bands.item(r, 0) else "").strip(),
                           "rate": round(self.bands.cellWidget(r, 1).value() / 100, 4)}
                          for r in range(self.bands.rowCount())]

    def _select(self, row):
        self._store_current()
        self._current = row
        self._refresh_list()
        self.list.blockSignals(True)
        self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        self.bands.setRowCount(0)
        if not (0 <= row < len(self.profiles)):
            return
        p = self.profiles[row]
        self.name_input.setText(p.get("name", ""))
        self.round_input.setChecked(bool(p.get("round_to_integer", True)))
        for band in p.get("bands", []):
            self._add_band(band.get("label", ""), band.get("rate", 1.0))

    def _add_band(self, label, rate):
        row = self.bands.rowCount()
        self.bands.insertRow(row)
        self.bands.setItem(row, 0, QTableWidgetItem(label))
        box = number_box(decimals=1, maximum=1000)
        box.setValue(float(rate) * 100)
        self.bands.setCellWidget(row, 1, box)

    def _remove_band(self):
        for row in sorted({i.row() for i in self.bands.selectedIndexes()}, reverse=True):
            self.bands.removeRow(row)

    def _add(self):
        self._store_current()
        profile = billing.default_weighting_profile()
        profile["name"] = "新加權表"
        self.profiles.append(profile)
        self._current = -1
        self._refresh_list()
        self.list.setCurrentRow(len(self.profiles) - 1)

    def _delete(self):
        if len(self.profiles) <= 1:
            QMessageBox.information(self, "提示", "至少要保留一個加權表。")
            return
        row = self.list.currentRow()
        removed = self.profiles.pop(row)
        if removed.get("id") == self.default_id:
            self.default_id = self.profiles[0].get("id")
        self._current = -1
        self._refresh_list()
        self.list.setCurrentRow(min(row, len(self.profiles) - 1))

    def _make_default(self):
        if 0 <= self._current < len(self.profiles):
            self.default_id = self.profiles[self._current].get("id")
            self._select(self._current)

    def result_profiles(self):
        self._store_current()
        return self.profiles, self.default_id


class ClientsPage(QWidget):
    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.clients = []
        self.config = None
        self._selected = None
        self._build_ui()
        self.reload()

    # --- 版面 ---

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)
        self.root = root
        title = QLabel("客戶與範本")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        # 寬的時候左右並排（清單｜內容）；窄的時候一次只顯示一邊，點客戶進入、按「返回」回清單
        self.body = QBoxLayout(QBoxLayout.LeftToRight)
        self.body.setSpacing(16)
        root.addLayout(self.body, 1)

        self.left = card(spacing=8, margins=(10, 10, 10, 10))
        self.list = QListWidget()
        self.list.setObjectName("clientList")
        self.list.currentItemChanged.connect(self._on_selection_changed)
        self.list.itemClicked.connect(lambda _item: self._open_detail())
        self.list.itemActivated.connect(lambda _item: self._open_detail())
        self.left.layout().addWidget(self.list, 1)
        self.show_archived = QCheckBox("顯示已封存的客戶")
        self.show_archived.toggled.connect(lambda _c: self.save_current(quiet=True) and self.reload(keep=self._selected))
        self.left.layout().addWidget(self.show_archived)
        row = QHBoxLayout()
        add_btn = button("新增客戶", primary=True)
        add_btn.clicked.connect(self._add_client)
        delete_btn = button("刪除")
        delete_btn.setToolTip("刪除選取的客戶")
        delete_btn.clicked.connect(self._delete_client)
        row.addWidget(add_btn, 1)
        row.addWidget(delete_btn)
        self.left.layout().addLayout(row)
        self.body.addWidget(self.left)

        self.right = QScrollArea()
        self.right.setWidgetResizable(True)
        self.right.setFrameShape(QFrame.NoFrame)
        self.right.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        detail = QWidget()
        detail.setObjectName("contentArea")
        self.right.setWidget(detail)
        right_layout = QVBoxLayout(detail)
        right_layout.setContentsMargins(0, 0, 4, 0)
        right_layout.setSpacing(14)
        self.back_btn = button("‹ 客戶清單", link=True)
        self.back_btn.clicked.connect(self._close_detail)
        right_layout.addWidget(self.back_btn, 0, Qt.AlignLeft)
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 700;")
        self.title_label.setWordWrap(True)
        right_layout.addWidget(self.title_label)
        self.summary_label = label("", muted=True, wrap=True)
        right_layout.addWidget(self.summary_label)

        self.info_group = card(spacing=10)
        self.info_group.layout().addWidget(label("客戶資料", role="h2"))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        self.name_input = QLineEdit()
        self.contact_input = QLineEdit()
        self.email_input = QLineEdit()
        self.currency_input = QComboBox()
        self.currency_input.setEditable(True)
        self.currency_input.addItems(CURRENCIES)
        _shrinkable(self.currency_input)
        self.terms_input = QLineEdit()
        self.terms_input.setPlaceholderText("例如：月結 30 天")
        self.notes_input = QTextEdit()
        self.notes_input.setMaximumHeight(70)
        self.archived_input = QCheckBox("封存這位客戶")
        self.archived_input.setToolTip("封存後，新增任務時不會出現在客戶清單（舊任務不受影響）")
        form.addRow("名稱", self.name_input)
        form.addRow("聯絡人", self.contact_input)
        form.addRow("Email", self.email_input)
        form.addRow("預設幣別", self.currency_input)
        form.addRow("付款條件", self.terms_input)
        form.addRow("備註", self.notes_input)
        self.info_group.layout().addLayout(form)
        self.info_group.layout().addWidget(self.archived_input)
        right_layout.addWidget(self.info_group)

        weight_card = card(spacing=8)
        self.profile_label = label("加權表", role="h2")
        weight_card.layout().addWidget(self.profile_label)
        weight_row = QHBoxLayout()
        self.profile_input = QComboBox()
        _shrinkable(self.profile_input)
        weight_row.addWidget(self.profile_input, 1)
        manage_btn = button("管理…")
        manage_btn.setToolTip("新增或修改加權表")
        manage_btn.clicked.connect(self._manage_profiles)
        weight_row.addWidget(manage_btn)
        weight_card.layout().addLayout(weight_row)
        right_layout.addWidget(weight_card)

        terms_group = card(spacing=10)
        terms_group.layout().addWidget(label("結算與收款", role="h2"))
        self.use_general_terms = QCheckBox("使用通用設定")
        self.use_general_terms.toggled.connect(self._on_use_general_terms)
        terms_group.layout().addWidget(self.use_general_terms)
        self.rule_editor = PaymentRuleEditor()
        terms_group.layout().addWidget(self.rule_editor)
        holidays_btn = button("管理假日行事曆…")
        holidays_btn.clicked.connect(self._manage_holidays)
        terms_group.layout().addWidget(holidays_btn, 0, Qt.AlignLeft)
        right_layout.addWidget(terms_group)

        rates_group = card(spacing=10)
        rates_group.layout().addWidget(label("常用單價範本", role="h2"))
        self.rates_help = label("", muted=True, wrap=True)
        rates_group.layout().addWidget(self.rates_help)
        self.rates_table = RatesTable()
        self.rates_table.setMinimumHeight(200)
        rates_group.layout().addWidget(self.rates_table, 1)
        rate_buttons = QHBoxLayout()
        add_rate = button("新增範本")
        add_rate.clicked.connect(lambda: self.rates_table.add_rate())
        remove_rate = button("刪除選取")
        remove_rate.clicked.connect(self.rates_table.remove_selected)
        rate_buttons.addWidget(add_rate)
        rate_buttons.addWidget(remove_rate)
        rate_buttons.addStretch()
        rates_group.layout().addLayout(rate_buttons)
        right_layout.addWidget(rates_group, 1)

        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = button("儲存變更", primary=True)
        save_btn.setMinimumWidth(120)
        save_btn.clicked.connect(lambda: self.save_current())
        save_row.addWidget(save_btn)
        right_layout.addLayout(save_row)
        self.body.addWidget(self.right, 1)

        self.compact = None
        self.detail_open = False

    # --- 寬窄版面 ---

    COMPACT = 700

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        width = self.width()
        side = 28 if width >= 640 else 16
        self.root.setContentsMargins(side, 24, side, 20)
        compact = width < self.COMPACT
        if compact == self.compact:
            return
        self.compact = compact
        self.rates_table.set_compact(compact)
        if compact:
            self.left.setMinimumWidth(0)
            self.left.setMaximumWidth(16777215)
        else:
            self.left.setFixedWidth(240)
        self._apply_detail_visibility()

    def _apply_detail_visibility(self):
        if self.compact:
            self.left.setVisible(not self.detail_open)
            self.right.setVisible(self.detail_open)
        else:
            self.left.setVisible(True)
            self.right.setVisible(True)
        self.back_btn.setVisible(bool(self.compact))

    def _open_detail(self):
        if self.compact and not self.detail_open:
            self.detail_open = True
            self._apply_detail_visibility()
            self.right.verticalScrollBar().setValue(0)

    def _close_detail(self):
        if self.save_current(quiet=True):
            self.detail_open = False
            self._apply_detail_visibility()

    # --- 資料 ---

    def reload(self, keep=None):
        self.clients = self.data_manager.load_clients()
        self.config = self.data_manager.load_billing()
        self.calendars = self.data_manager.load_holidays()
        self.rule_editor.set_calendars(self.calendars)
        self.list.blockSignals(True)
        self.list.clear()
        general = QListWidgetItem("＊ 通用範本（所有客戶共用）")
        general.setData(Qt.UserRole, GENERAL)
        self.list.addItem(general)
        for c in sorted(self.clients, key=lambda c: c.name):
            if c.archived and not self.show_archived.isChecked():
                continue
            item = QListWidgetItem(c.name + ("（已封存）" if c.archived else ""))
            item.setData(Qt.UserRole, c.id)
            self.list.addItem(item)
        self.list.blockSignals(False)
        target = keep or GENERAL
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == target:
                self.list.setCurrentRow(i)
                break
        else:
            self.list.setCurrentRow(0)
        self._show(self.list.currentItem().data(Qt.UserRole))

    def _client(self, client_id):
        return next((c for c in self.clients if c.id == client_id), None)

    def _fill_profiles(self, selected_id, allow_default):
        self.profile_input.clear()
        if allow_default:
            self.profile_input.addItem("使用預設加權表", "")
        for p in self.config.weighting_profiles:
            self.profile_input.addItem(p.get("name", ""), p.get("id"))
        self.profile_input.setCurrentIndex(max(0, self.profile_input.findData(selected_id)))

    def _show(self, key):
        self._selected = key
        if key == GENERAL:
            self.title_label.setText("通用範本")
            self.summary_label.setText("新增任務時，客戶沒有設定的項目會從這裡帶入。")
            self.info_group.setVisible(False)
            self.profile_label.setText("預設加權表")
            self._fill_profiles(self.config.default_weighting_profile_id, allow_default=False)
            self.rates_help.setText("所有客戶共用的單價。客戶有同名範本時，以客戶的為準。")
            self.rates_table.load(self.config.rates)
            self.use_general_terms.setVisible(False)
            self.rule_editor.setEnabled(True)
            self.rule_editor.set_rule(self.config.payment_rule)
            return
        client = self._client(key)
        if client is None:
            return
        self.info_group.setVisible(True)
        self.title_label.setText(client.name)
        s = tasks_service.client_summary(self.data_manager.load_tasks(), client)
        self.summary_label.setText(
            f"合作案件 {s['count']} 件（進行中 {s['in_progress']} 件）　"
            f"待收款 {_money(s['receivable'])}　已收款 {_money(s['paid'])}")
        self.name_input.setText(client.name)
        self.contact_input.setText(client.contact)
        self.email_input.setText(client.email)
        self.currency_input.setCurrentText(client.currency or "NTD")
        self.terms_input.setText(client.payment_terms)
        self.notes_input.setPlainText(client.notes)
        self.archived_input.setChecked(client.archived)
        self.profile_label.setText("加權表")
        self._fill_profiles(client.weighting_profile_id, allow_default=True)
        self.rates_help.setText("新增任務時選擇這位客戶，會優先帶入以下單價；沒列出的項目沿用通用範本。")
        self.rates_table.load(client.rates)
        uses_general = not isinstance(client.payment_rule, dict)
        self.use_general_terms.setVisible(True)
        self.use_general_terms.blockSignals(True)
        self.use_general_terms.setChecked(uses_general)
        self.use_general_terms.blockSignals(False)
        self.rule_editor.set_rule(self.config.rule_for(client))
        self.rule_editor.setEnabled(not uses_general)

    def _on_use_general_terms(self, checked):
        self.rule_editor.setEnabled(not checked)
        if checked:
            self.rule_editor.set_rule(self.config.payment_rule)

    def _on_selection_changed(self, current, previous):
        if previous is not None and not self.save_current(quiet=True):
            self.list.blockSignals(True)
            self.list.setCurrentItem(previous)
            self.list.blockSignals(False)
            return
        if current is not None:
            self._show(current.data(Qt.UserRole))

    def save_current(self, quiet=False) -> bool:
        key = self._selected
        unnamed = self.rates_table.unnamed_row()
        if unnamed is not None:
            # 沒有名稱的範本存檔時會被略過；有填單價的話先提醒，避免默默不見
            if self.compact:
                self.detail_open = True
                self._apply_detail_visibility()
            self.rates_table.selectRow(unnamed)
            self.right.ensureWidgetVisible(self.rates_table)
            QMessageBox.warning(self, "提示", f"單價範本第 {unnamed + 1} 列還沒有填項目名稱。\n"
                                "請輸入名稱，或選取這一列後按「刪除選取」。")
            return False
        if key == GENERAL:
            self.config.rates = self.rates_table.rates()
            self.config.default_weighting_profile_id = self.profile_input.currentData() or ""
            self.config.payment_rule = self.rule_editor.rule()
            self.data_manager.save_billing(self.config)
            self._recompute_task_dates()
            if not quiet:
                QMessageBox.information(self, "提示", "已儲存通用範本。")
            return True
        client = self._client(key)
        if client is None:
            return True
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "客戶名稱不能空白。")
            return False
        if any(c.name.strip() == name and c.id != client.id for c in self.clients):
            QMessageBox.warning(self, "提示", f"已經有一位叫「{name}」的客戶了。")
            return False
        renamed = client.name != name
        client.name = name
        client.contact = self.contact_input.text().strip()
        client.email = self.email_input.text().strip()
        client.currency = self.currency_input.currentText().strip() or "NTD"
        client.payment_terms = self.terms_input.text().strip()
        client.notes = self.notes_input.toPlainText()
        client.archived = self.archived_input.isChecked()
        client.weighting_profile_id = self.profile_input.currentData() or ""
        client.rates = self.rates_table.rates()
        client.payment_rule = None if self.use_general_terms.isChecked() else self.rule_editor.rule()
        self.data_manager.save_clients(self.clients)
        tasks = self.data_manager.load_tasks()
        renamed_tasks = renamed and tasks_service.rename_client(tasks, client)
        redated = tasks_service.recompute_billing_dates(tasks, self.clients, self.config, self.calendars)
        if renamed_tasks or redated:
            self.data_manager.save_tasks(tasks)
        current = self.list.currentItem()
        if current is not None and current.data(Qt.UserRole) == client.id:
            current.setText(client.name + ("（已封存）" if client.archived else ""))
        self.title_label.setText(client.name)
        if not quiet:
            QMessageBox.information(self, "提示", f"已儲存「{client.name}」。")
        return True

    def _recompute_task_dates(self):
        tasks = self.data_manager.load_tasks()
        if tasks_service.recompute_billing_dates(tasks, self.clients, self.config, self.calendars):
            self.data_manager.save_tasks(tasks)

    # --- 操作 ---

    def _add_client(self):
        if not self.save_current(quiet=True):
            return
        base, n = "新客戶", 1
        names = {c.name for c in self.clients}
        name = base
        while name in names:
            n += 1
            name = f"{base} {n}"
        client = Client(id=billing.new_id(), name=name,
                        currency=self.data_manager.load_settings().default_currency or "NTD")
        self.clients.append(client)
        self.data_manager.save_clients(self.clients)
        self.reload(keep=client.id)
        self.name_input.setFocus()
        self.name_input.selectAll()

    def _delete_client(self):
        client = self._client(self._selected)
        if client is None:
            return
        summary = tasks_service.client_summary(self.data_manager.load_tasks(), client)
        if summary["count"]:
            answer = QMessageBox.question(
                self, "封存客戶",
                f"「{client.name}」有 {summary['count']} 件任務，不能刪除。\n要改成封存嗎？封存後新增任務時不會再出現這位客戶。")
            if answer == QMessageBox.Yes:
                client.archived = True
                self.data_manager.save_clients(self.clients)
                self.reload()
            return
        if QMessageBox.question(self, "刪除客戶", f"確定要刪除「{client.name}」嗎？") == QMessageBox.Yes:
            self.clients.remove(client)
            self.data_manager.save_clients(self.clients)
            self._selected = None
            self.reload()

    def _manage_holidays(self):
        if not self.save_current(quiet=True):
            return
        dialog = HolidayCalendarsDialog(self.calendars, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.calendars = dialog.result_calendars()
        self.data_manager.save_holidays(self.calendars)
        self.rule_editor.set_calendars(self.calendars)
        self._recompute_task_dates()
        self._show(self._selected)

    def _manage_profiles(self):
        if not self.save_current(quiet=True):
            return
        dialog = WeightingProfilesDialog(self.config.weighting_profiles, self.config.default_weighting_profile_id, self)
        if dialog.exec() != QDialog.Accepted:
            return
        profiles, default_id = dialog.result_profiles()
        self.config.weighting_profiles = profiles
        self.config.default_weighting_profile_id = default_id
        self.data_manager.save_billing(self.config)
        valid = {p.get("id") for p in profiles}
        changed = False
        for c in self.clients:
            if c.weighting_profile_id and c.weighting_profile_id not in valid:
                c.weighting_profile_id = ""
                changed = True
        if changed:
            self.data_manager.save_clients(self.clients)
        self._show(self._selected)
