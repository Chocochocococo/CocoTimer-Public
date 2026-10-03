"""新增／編輯任務對話框（v3：分區排版、四段式狀態、可刪除任務）。"""
from PySide6.QtCore import QDate, QTime, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSlider, QSpinBox, QTextEdit, QTimeEdit, QToolButton,
                               QVBoxLayout, QWidget)

from cocotimer import billing, holidays, payment_terms
from cocotimer import tasks as tasks_service
from cocotimer.ui.billing_widgets import COLUMN_STRETCH, PriceItemRow
from cocotimer.ui.widgets import button, card, label

CURRENCIES = ["NTD", "USD", "JPY", "EUR", "CNY", "HKD", "GBP"]
STEP_DATES = {tasks_service.DELIVERED: "delivered_date", tasks_service.INVOICED: "invoiced_date",
              tasks_service.PAID: "paid_date"}


def _field(text, widget):
    """上方是小標題、下方是輸入框的欄位。"""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    title = label(text, muted=True)
    title.setBuddy(widget)
    layout.addWidget(title)
    layout.addWidget(widget)
    return box


class StatusStepper(QWidget):
    """四段式狀態：進行中 → 已交付 → 已請款 → 已收款。介面跟 QComboBox 相容（currentData、findData…）。"""
    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.group = QButtonGroup(self)
        self.keys = [key for key, _ in tasks_service.STATUSES]
        self.buttons = []
        self.dates = {}
        for i, (key, text) in enumerate(tasks_service.STATUSES):
            btn = QPushButton()
            btn.setProperty("step", True)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(52)
            btn.clicked.connect(lambda _c=False, idx=i: self._clicked(idx))
            self.group.addButton(btn, i)
            self.buttons.append(btn)
            layout.addWidget(btn, 1)
        self._index = 0
        self._render()

    def _clicked(self, index):
        if index != self._index:
            self._index = index
            self._render()
            if not self.signalsBlocked():
                self.currentIndexChanged.emit(index)

    def set_dates(self, dates):
        self.dates = dates
        self._render()

    def _render(self):
        for i, (btn, (key, text)) in enumerate(zip(self.buttons, tasks_service.STATUSES)):
            mark = "✓" if i < self._index else str(i + 1)
            when = self.dates.get(key, "")
            sub = (when[5:].replace("-", "/") if when else "—") if key != tasks_service.IN_PROGRESS else "開始處理"
            btn.setText(f"{mark}  {text}\n     {sub}")
            btn.setChecked(i == self._index)

    def currentData(self):
        return self.keys[self._index]

    def currentIndex(self):
        return self._index

    def findData(self, key):
        return self.keys.index(key) if key in self.keys else -1

    def setCurrentIndex(self, index):
        if 0 <= index < len(self.keys) and index != self._index:
            self._clicked(index)
        else:
            self._render()


class TaskEditDialog(QDialog):
    """任務編輯對話框。on_delete（可省略）會在使用者按「刪除任務」並確認後被呼叫。"""

    def __init__(self, data_manager, task=None, parent=None, on_delete=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.task = task
        self.on_delete = on_delete
        self.rows = []
        self.clients = data_manager.load_clients()
        self.billing_config = data_manager.load_billing()
        self.calendars = data_manager.load_holidays()
        self.setWindowTitle("編輯任務" if task else "新增任務")
        self.setMinimumSize(840, 600)
        self._build_ui()
        if self.task:
            self._load_task_data()
        else:
            self._add_row()
        self._rebuild_template_menu()
        self._refresh_billing_dates()
        self._calculate_total()
        # 恢復上次儲存的視窗尺寸
        self.data_manager.restore_window_geometry("task_edit_dialog", self)
        if self.width() < 840 or self.height() < 600:
            self.resize(980, 820)

    # --- 版面 ---

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setObjectName("contentArea")
        body = QVBoxLayout(content)
        body.setContentsMargins(24, 20, 24, 20)
        body.setSpacing(16)

        title = QLabel(self.windowTitle())
        title.setObjectName("pageTitle")
        body.addWidget(title)
        if self.task and self.task.created_date:
            body.addWidget(label(f"建立於 {self.task.created_date.replace('-', '/')} {self.task.created_time}", muted=True))

        body.addWidget(self._build_basic_section())
        body.addWidget(self._build_status_section())
        body.addWidget(self._build_price_group())
        body.addWidget(self._build_dates_section())

        notes = card(spacing=8)
        notes.layout().addWidget(label("備註", role="h2"))
        self.desc_input = QTextEdit()
        self.desc_input.setMinimumHeight(70)
        self.desc_input.setMaximumHeight(110)
        self.desc_input.setPlaceholderText("例如參考資料、交件方式、聯絡紀錄……")
        self.desc_input.setTabChangesFocus(True)
        notes.layout().addWidget(self.desc_input)
        body.addWidget(notes)
        body.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        footer = QFrame()
        footer.setProperty("card", True)
        footer.setStyleSheet("QFrame { border-radius: 0; border-left: none; border-right: none; border-bottom: none; }")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(20, 12, 20, 12)
        if self.task and self.on_delete:
            delete_btn = button("刪除任務", link=True, danger=True)
            delete_btn.clicked.connect(self._delete)
            buttons.addWidget(delete_btn)
        buttons.addStretch()
        cancel_btn = button("取消")
        cancel_btn.setMinimumWidth(96)
        cancel_btn.clicked.connect(self.reject)
        save_btn = button("儲存", primary=True)
        save_btn.setMinimumWidth(110)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        layout.addWidget(footer)

    def _build_basic_section(self):
        section = card(spacing=12)
        section.layout().addWidget(label("基本資訊", role="h2"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        self.project_input = QLineEdit()
        self.project_input.setPlaceholderText("例如：星海旅人")
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("例如：第三集封面")

        self.client_input = QComboBox()
        self.client_input.setEditable(True)
        self.client_input.lineEdit().setPlaceholderText("選擇或輸入新客戶")
        self.client_input.addItem("")
        for client in self.clients:
            if not client.archived:
                self.client_input.addItem(client.name, client.id)
        self.client_input.currentTextChanged.connect(self._on_client_changed)
        self.currency_input = QComboBox()
        self.currency_input.setEditable(True)
        self.currency_input.addItems(CURRENCIES)
        self.currency_input.setCurrentText(self.data_manager.load_settings().default_currency or "NTD")
        self.currency_input.currentTextChanged.connect(lambda _t: self._calculate_total())

        self.due_date_input = QDateEdit(QDate.currentDate())
        self.due_date_input.setCalendarPopup(True)
        self.due_date_input.setDisplayFormat("yyyy/MM/dd")
        self.due_time_input = QTimeEdit(QTime(23, 59))
        self.due_time_input.setDisplayFormat("HH:mm")
        due_row = QWidget()
        due_layout = QHBoxLayout(due_row)
        due_layout.setContentsMargins(0, 0, 0, 0)
        due_layout.addWidget(self.due_date_input, 3)
        due_layout.addWidget(self.due_time_input, 2)

        remind_row = QWidget()
        remind_layout = QHBoxLayout(remind_row)
        remind_layout.setContentsMargins(0, 0, 0, 0)
        self.remind_checkbox = QCheckBox("提前")
        self.remind_minutes_input = QSpinBox()
        self.remind_minutes_input.setRange(1, 10080)
        self.remind_minutes_input.setValue(30)
        self.remind_minutes_input.setSuffix(" 分鐘提醒")
        remind_layout.addWidget(self.remind_checkbox)
        remind_layout.addWidget(self.remind_minutes_input, 1)

        self.client_hint = label("", muted=True, wrap=True)
        client_box = _field("客戶", self.client_input)
        client_box.layout().addWidget(self.client_hint)

        for widget, row, col in ((_field("專案名稱", self.project_input), 0, 0), (_field("任務標題", self.title_input), 0, 1),
                                 (client_box, 1, 0), (_field("幣別", self.currency_input), 1, 1),
                                 (_field("交件日期與時間", due_row), 2, 0), (_field("提醒", remind_row), 2, 1)):
            grid.addWidget(widget, row, col, Qt.AlignTop)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        section.layout().addLayout(grid)
        return section

    def _build_status_section(self):
        section = card(spacing=12)
        section.layout().addWidget(label("狀態與進度", role="h2"))
        self.status_input = StatusStepper()
        self.status_input.currentIndexChanged.connect(self._on_status_changed)
        section.layout().addWidget(self.status_input)
        row = QHBoxLayout()
        row.addWidget(label("完成度", muted=True))
        self.completion_slider = QSlider(Qt.Horizontal)
        self.completion_slider.setRange(0, 100)
        self.completion_slider.setSingleStep(5)
        self.completion_slider.setPageStep(10)
        self.completion_slider.valueChanged.connect(self._on_completion_changed)
        row.addWidget(self.completion_slider, 1)
        self.completion_label = label("0%", role="mono")
        self.completion_label.setMinimumWidth(48)
        self.completion_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.completion_label)
        section.layout().addLayout(row)
        section.layout().addWidget(label("狀態改成「已收款」時，金額會從待收款移到已收款。", muted=True))
        return section

    def _build_dates_section(self):
        section = card(spacing=10)
        head = QHBoxLayout()
        head.addWidget(label("結算與收款", role="h2"))
        head.addStretch()
        self.dates_auto = QCheckBox("依客戶規則自動計算")
        self.dates_auto.setChecked(True)
        head.addWidget(self.dates_auto)
        section.layout().addLayout(head)
        self.settlement_input = QDateEdit(QDate.currentDate())
        self.settlement_input.setCalendarPopup(True)
        self.settlement_input.setDisplayFormat("yyyy/MM/dd")
        self.payment_input = QDateEdit(QDate.currentDate())
        self.payment_input.setCalendarPopup(True)
        self.payment_input.setDisplayFormat("yyyy/MM/dd")
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(_field("結算日", self.settlement_input), 1)
        row.addWidget(_field("預計收款日", self.payment_input), 1)
        section.layout().addLayout(row)
        self.dates_hint = label("", muted=True, wrap=True)
        section.layout().addWidget(self.dates_hint)
        self.due_date_input.dateChanged.connect(lambda _d: self._refresh_billing_dates())
        self.dates_auto.toggled.connect(lambda _c: self._refresh_billing_dates())
        return section

    def _build_price_group(self):
        section = card(spacing=10)
        section.layout().addWidget(label("費用明細", role="h2"))
        section.layout().addWidget(label("每一項可以分別選「簡單」、「委託與計費分開」或「加權計算」。", muted=True, wrap=True))

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 0, 5, 0)
        header_layout.setSpacing(6)
        for key, text in (("name", "項目名稱"), ("unit", "單位"), ("price", "單價"), ("mode", "計費方式"),
                          ("qty", "委託數量"), ("billable", "計費數量"), ("subtotal", "小計")):
            head = label(text, muted=True)
            head.setStyleSheet("font-size: 12px;")
            if key == "subtotal":
                head.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            header_layout.addWidget(head, COLUMN_STRETCH[key])
        spacer = QLabel("")
        spacer.setFixedWidth(60)
        header_layout.addWidget(spacer)
        section.layout().addWidget(header)

        container = QWidget()
        self.rows_layout = QVBoxLayout(container)
        self.rows_layout.setContentsMargins(5, 0, 5, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch()
        section.layout().addWidget(container)

        actions = QHBoxLayout()
        add_btn = button("+ 新增項目")
        add_btn.clicked.connect(lambda: self._add_row())
        actions.addWidget(add_btn)
        self.template_btn = QToolButton()
        self.template_btn.setProperty("textButton", True)
        self.template_btn.setText("從範本加入  ▾")
        self.template_btn.setPopupMode(QToolButton.InstantPopup)
        self.template_btn.setMenu(QMenu(self.template_btn))
        self.template_btn.setCursor(Qt.PointingHandCursor)
        actions.addWidget(self.template_btn)
        actions.addStretch()
        self.total_price_label = QLabel()
        self.total_price_label.setStyleSheet("font-weight: 700; font-size: 15px;")
        self.total_price_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.total_price_label.setWordWrap(True)
        actions.addWidget(self.total_price_label, 1)
        section.layout().addLayout(actions)
        self.focus_label = label("", muted=True, wrap=True)
        self.focus_label.setAlignment(Qt.AlignRight)
        self.focus_label.setVisible(False)
        section.layout().addWidget(self.focus_label)
        return section

    def _delete(self):
        if self.on_delete and self.on_delete(self.task):
            super().reject()

    # --- 價格項目 ---

    def _current_client(self):
        return tasks_service.find_client(self.clients, client_id=self.client_input.currentData() or "",
                                         name=self.client_input.currentText())

    def _current_profile(self):
        return self.billing_config.profile_for(self._current_client())

    def _add_row(self, item=None):
        row = PriceItemRow(self._current_profile, lambda: self.billing_config.weighting_profiles)
        if item is not None:
            row.load(item)
        row.changed.connect(self._calculate_total)
        row.remove_requested.connect(self._remove_row)
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        self.rows.append(row)
        self._calculate_total()
        return row

    def _remove_row(self, row):
        if row in self.rows:
            self.rows.remove(row)
            row.deleteLater()
        self._calculate_total()

    def _rebuild_template_menu(self):
        menu = self.template_btn.menu()
        menu.clear()
        client = self._current_client()
        client_rates = list(client.rates) if client else []
        own_names = {r.get("name") for r in client_rates}
        general = [r for r in self.billing_config.rates if r.get("name") not in own_names]
        for title, rates in ((f"{client.name} 的範本" if client else None, client_rates), ("通用範本", general)):
            if not rates:
                continue
            menu.addSection(title)
            for rate in rates:
                unit = f" / {rate.get('unit')}" if rate.get("unit") else ""
                label = (f"{rate.get('name', '')}　{billing.format_number(rate.get('unit_price', 0))}{unit}"
                         f"（{billing.BILLING_LABELS.get(rate.get('billing'), '簡單')}）")
                menu.addAction(label, lambda r=rate: self._add_from_rate(r))
        if menu.isEmpty():
            action = menu.addAction("還沒有範本，可以到「客戶」分頁新增")
            action.setEnabled(False)

    def _add_from_rate(self, rate):
        item = billing.item_from_rate(rate, self._current_profile())
        blank = next((r for r in self.rows if r.is_blank()), None)
        if blank is not None:
            blank.load(item)
            self._calculate_total()
        else:
            self._add_row(item)

    def _calculate_total(self):
        items = [r.to_item() for r in self.rows if not r.is_blank()]
        parts = []
        split_items = [i for i in items if i["billing"] != billing.SIMPLE]
        if split_items:
            for q in billing.quantity_summary(split_items):
                if q["quantity"] != q["billable"]:
                    parts.append(f"委託 {billing.format_number(q['quantity'])}{q['unit']}"
                                 f" → 計費 {billing.format_number(q['billable'])}{q['unit']}")
        currency = self.currency_input.currentText().strip() or "NTD"
        total = billing.items_total(items)
        parts.append(f"總價: {currency} {total:,.2f}")
        self.total_price_label.setText("　·　".join(parts))
        seconds = tasks_service.focus_seconds(self.task) if self.task else 0
        self.focus_label.setVisible(seconds >= 60)
        if seconds >= 60:
            text = f"番茄鐘專注 {tasks_service.focus_text(seconds)}"
            if total and seconds >= 600:
                text += f"　·　時薪約 {currency} {total / (seconds / 3600):,.0f}"
            self.focus_label.setText(text)

    # --- 客戶／狀態 ---

    def _on_client_changed(self, _text):
        client = self._current_client()
        if client and not self.task:
            self.currency_input.setCurrentText(client.currency or "NTD")
        name = self.client_input.currentText().strip()
        if client:
            own = len(client.rates)
            self.client_hint.setText(f"「從範本加入」會優先列出這位客戶的 {own} 個範本。" if own else "這位客戶還沒有專屬範本，會列出通用範本。")
        else:
            self.client_hint.setText(f"存檔時會建立新客戶「{name}」。" if name else "")
        self._rebuild_template_menu()
        self._refresh_billing_dates()
        self._calculate_total()

    def _refresh_billing_dates(self):
        client = self._current_client()
        rule = self.billing_config.rule_for(client)
        auto = self.dates_auto.isChecked()
        self.settlement_input.setEnabled(not auto)
        self.payment_input.setEnabled(not auto)
        source = f"「{client.name}」" if client and isinstance(client.payment_rule, dict) else "通用設定"
        if not auto:
            self.dates_hint.setText("手動設定結算日與收款日")
            return
        is_off = holidays.make_is_off(self.calendars, rule["calendar_ids"])
        settled, paid = payment_terms.compute_dates(self.due_date_input.date().toString("yyyy-MM-dd"), rule, is_off)
        self.settlement_input.setDate(QDate.fromString(settled, "yyyy-MM-dd"))
        self.payment_input.setDate(QDate.fromString(paid, "yyyy-MM-dd"))
        hint = f"{source}：{payment_terms.describe_rule(rule)}"
        missing = holidays.missing_years(self.calendars, rule["calendar_ids"], {int(settled[:4]), int(paid[:4])}) if settled else {}
        for name, years in missing.items():
            hint += f"\n⚠ 「{name}」還沒有 {'、'.join(map(str, years))} 年的資料，這一年只依週六、週日判斷（可到「客戶」分頁匯入）"
        self.dates_hint.setText(hint)

    def _on_status_changed(self, _index):
        if self.status_input.currentData() != tasks_service.IN_PROGRESS:
            self.completion_slider.setValue(100)
        elif self.completion_slider.value() >= 100:
            self.completion_slider.setValue(90)

    def _on_completion_changed(self, value):
        self.completion_label.setText(f"{value}%")
        status = self.status_input.currentData()
        if value < 100 and status != tasks_service.IN_PROGRESS:
            self.status_input.setCurrentIndex(self.status_input.findData(tasks_service.IN_PROGRESS))
        elif value >= 100 and status == tasks_service.IN_PROGRESS:
            self.status_input.setCurrentIndex(self.status_input.findData(tasks_service.DELIVERED))

    # --- 載入／取得資料 ---

    def _load_task_data(self):
        task = self.task
        self.project_input.setText(task.project_name)
        self.title_input.setText(task.title)
        self.due_date_input.setDate(QDate.fromString(task.due_date, "yyyy-MM-dd"))
        self.due_time_input.setTime(QTime.fromString(task.due_time, "HH:mm"))
        client = tasks_service.find_client(self.clients, task.client_id, task.client)
        self.client_input.setCurrentText(client.name if client else task.client)
        self.currency_input.setCurrentText(task.currency or "NTD")
        self.desc_input.setPlainText(task.description)
        self.status_input.blockSignals(True)
        self.status_input.set_dates({key: getattr(task, attr) for key, attr in STEP_DATES.items()})
        self.status_input.setCurrentIndex(max(0, self.status_input.findData(task.status)))
        self.status_input.blockSignals(False)
        self.completion_slider.blockSignals(True)
        self.completion_slider.setValue(task.completion)
        self.completion_slider.blockSignals(False)
        self.completion_label.setText(f"{task.completion}%")
        self.dates_auto.blockSignals(True)
        self.dates_auto.setChecked(task.billing_dates_auto)
        self.dates_auto.blockSignals(False)
        if not task.billing_dates_auto:
            for box, value in ((self.settlement_input, task.settlement_date), (self.payment_input, task.payment_date)):
                if value:
                    box.setDate(QDate.fromString(value, "yyyy-MM-dd"))
        if task.remind_before > 0:
            self.remind_checkbox.setChecked(True)
            self.remind_minutes_input.setValue(task.remind_before)
        for item in task.price_items:
            self._add_row(item)
        if not self.rows:
            self._add_row()

    def _validate_required_fields(self) -> bool:
        if not self.project_input.text().strip():
            QMessageBox.warning(self, "提示", "請輸入專案名稱！")
            self.project_input.setFocus()
            return False
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "提示", "請輸入任務標題！")
            self.title_input.setFocus()
            return False
        for number, row in enumerate(self.rows, 1):
            if row.is_blank() and row.has_values():
                self.scroll.ensureWidgetVisible(row)
                QMessageBox.warning(self, "提示", f"第 {number} 個價格項目還沒有填名稱。\n"
                                    "請輸入項目名稱（例如「插畫」），或按「移除」刪掉這一列。")
                row.name_input.setFocus()
                return False
        return True

    def accept(self):
        if not self._validate_required_fields():
            return
        self._save_geometry()
        super().accept()

    def reject(self):
        self._save_geometry()
        super().reject()

    def closeEvent(self, event):
        self._save_geometry()
        super().closeEvent(event)

    def _save_geometry(self):
        self.data_manager.save_window_geometry("task_edit_dialog", self)

    def get_task_data(self):
        project = self.project_input.text().strip()
        title = self.title_input.text().strip()
        if not project or not title:
            return None
        return {
            'project_name': project,
            'title': title,
            'due_date': self.due_date_input.date().toString("yyyy-MM-dd"),
            'due_time': self.due_time_input.time().toString("HH:mm"),
            'client': self.client_input.currentText().strip(),
            'currency': self.currency_input.currentText().strip() or 'NTD',
            'description': self.desc_input.toPlainText(),
            'completion': self.completion_slider.value(),
            'status': self.status_input.currentData(),
            'billing_dates_auto': self.dates_auto.isChecked(),
            'settlement_date': self.settlement_input.date().toString("yyyy-MM-dd"),
            'payment_date': self.payment_input.date().toString("yyyy-MM-dd"),
            'price_items': [r.to_item() for r in self.rows if not r.is_blank()],
            'remind_before': self.remind_minutes_input.value() if self.remind_checkbox.isChecked() else 0,
        }
