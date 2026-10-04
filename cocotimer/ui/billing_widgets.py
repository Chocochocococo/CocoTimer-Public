"""計費相關的小元件：價格項目的一列、加權明細對話框、結算與收款規則。"""
from datetime import date
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout, QMenu, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from cocotimer import billing, holidays, payment_terms
from cocotimer.ui.widgets import FlowLayout

# 價格項目各欄的寬度比例，表頭與每一列共用
COLUMN_STRETCH = {"name": 3, "unit": 1, "price": 2, "mode": 2, "qty": 2, "billable": 2, "subtotal": 2}


def number_box(decimals=2, maximum=99_999_999.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(0, maximum)
    box.setGroupSeparatorShown(True)
    box.setAlignment(Qt.AlignRight)
    box.setButtonSymbols(QDoubleSpinBox.NoButtons)
    # 預設會依最大值（九位數）留寬度，費用明細一列放不下；改成放得下一般金額就好
    box.setMinimumWidth(box.fontMetrics().horizontalAdvance("99,999.00") + 18)
    return box


class PriceItemRow(QWidget):
    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, profile_getter: Callable[[], Optional[dict]],
                 profiles_getter: Callable[[], List[dict]], parent=None):
        super().__init__(parent)
        self._profile_getter = profile_getter
        self._profiles_getter = profiles_getter
        self.weighting: Optional[dict] = None
        self._extra: dict = {}
        self._loading = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("項目名稱")
        self.unit_input = QComboBox()
        self.unit_input.setEditable(True)
        self.unit_input.addItems(billing.UNITS)
        self.unit_input.setCurrentText("")
        self.price_input = number_box(decimals=3)
        self.mode_input = QComboBox()
        self.mode_input.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode_input.setMinimumContentsLength(6)
        for key, label in billing.BILLING_MODES:
            self.mode_input.addItem(label, key)
        self.qty_input = number_box()
        self.qty_input.setValue(1)
        self.billable_input = number_box()
        self.weight_btn = QToolButton()
        self.weight_btn.setProperty("textButton", True)
        self.weight_btn.setProperty("compact", True)
        self.weight_btn.setText("加權…")
        self.weight_btn.setToolTip("編輯加權明細")
        self.subtotal_label = QLabel("0")
        self.subtotal_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        remove_btn = QPushButton("移除")
        remove_btn.setMinimumWidth(60)
        remove_btn.setProperty("danger", True)
        remove_btn.setToolTip("移除這個項目")

        billable_box = QWidget()
        billable_layout = QHBoxLayout(billable_box)
        billable_layout.setContentsMargins(0, 0, 0, 0)
        billable_layout.setSpacing(2)
        billable_layout.addWidget(self.billable_input, 1)
        billable_layout.addWidget(self.weight_btn)

        layout.addWidget(self.name_input, COLUMN_STRETCH["name"])
        layout.addWidget(self.unit_input, COLUMN_STRETCH["unit"])
        layout.addWidget(self.price_input, COLUMN_STRETCH["price"])
        layout.addWidget(self.mode_input, COLUMN_STRETCH["mode"])
        layout.addWidget(self.qty_input, COLUMN_STRETCH["qty"])
        layout.addWidget(billable_box, COLUMN_STRETCH["billable"])
        layout.addWidget(self.subtotal_label, COLUMN_STRETCH["subtotal"])
        layout.addWidget(remove_btn)

        self.name_input.textChanged.connect(self._emit_changed)
        self.unit_input.currentTextChanged.connect(self._emit_changed)
        self.price_input.valueChanged.connect(self._refresh)
        self.qty_input.valueChanged.connect(self._on_qty_changed)
        self.billable_input.valueChanged.connect(self._refresh)
        self.mode_input.currentIndexChanged.connect(self._on_mode_changed)
        self.weight_btn.clicked.connect(self.edit_weighting)
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        self._apply_mode_state()
        self._refresh()

    # --- 資料 ---

    def load(self, item: dict):
        item = billing.normalize_item(item)
        known = {"name", "unit", "unit_price", "quantity", "billing", "billable_quantity", "weighting"}
        self._extra = {k: v for k, v in item.items() if k not in known}
        self._loading = True
        self.name_input.setText(item["name"])
        self.unit_input.setCurrentText(item["unit"])
        self.price_input.setValue(item["unit_price"])
        self.weighting = item.get("weighting")
        self.mode_input.setCurrentIndex(max(0, self.mode_input.findData(item["billing"])))
        self.qty_input.setValue(item["quantity"])
        bq = item.get("billable_quantity")
        self.billable_input.setValue(item["quantity"] if bq is None else bq)
        self._loading = False
        self._apply_mode_state()
        self._refresh()

    def mode(self) -> str:
        return self.mode_input.currentData()

    def to_item(self) -> dict:
        mode = self.mode()
        item = {**self._extra,
                "name": self.name_input.text().strip(),
                "unit": self.unit_input.currentText().strip(),
                "unit_price": self.price_input.value(),
                "quantity": self.qty_input.value(),
                "billing": mode,
                "billable_quantity": self.billable_input.value() if mode != billing.SIMPLE else None,
                "weighting": self.weighting if mode == billing.WEIGHTED else None}
        return billing.normalize_item(item)

    def is_blank(self) -> bool:
        return not self.name_input.text().strip()

    def has_values(self) -> bool:
        """有填單價或加權數量（不管有沒有名稱）。沒名稱卻有數字的項目存檔前要提醒，不然會被當成空白列丟掉。"""
        return self.price_input.value() != 0 or (self.mode() == billing.WEIGHTED and bool(self.weighting))

    # --- 互動 ---

    def _emit_changed(self, *_):
        if not self._loading:
            self.changed.emit()

    def _on_qty_changed(self, value):
        # 「委託與計費分開」時，計費數量還跟委託數量一樣的話就一起更新
        if self.mode() == billing.MANUAL and not self._loading and self.billable_input.value() == self._last_qty:
            self.billable_input.setValue(value)
        self._refresh()

    def _on_mode_changed(self, _index):
        if self._loading:
            return
        mode = self.mode()
        if mode == billing.MANUAL:
            self.billable_input.setValue(self.qty_input.value())
        if mode == billing.WEIGHTED and self.weighting is None:
            profile = self._profile_getter()
            if profile is None:
                self.mode_input.setCurrentIndex(self.mode_input.findData(billing.MANUAL))
                return
            self.weighting = billing.weighting_from_profile(profile)
            self._apply_mode_state()
            if not self.edit_weighting() and self.weighting_is_empty():
                self.weighting = None
                self.mode_input.setCurrentIndex(self.mode_input.findData(billing.MANUAL))
                return
        self._apply_mode_state()
        self._refresh()

    def weighting_is_empty(self) -> bool:
        return not self.weighting or billing.weighted_source_quantity(self.weighting) == 0

    def edit_weighting(self) -> bool:
        dialog = WeightingDialog(self._profiles_getter(), self.weighting, self)
        if dialog.exec() != QDialog.Accepted:
            return False
        self.weighting = dialog.weighting()
        self._refresh()
        return True

    def _apply_mode_state(self):
        mode = self.mode()
        weighted = mode == billing.WEIGHTED
        self.qty_input.setReadOnly(weighted)
        self.billable_input.setEnabled(mode != billing.SIMPLE)
        self.billable_input.setReadOnly(weighted)
        self.weight_btn.setVisible(weighted)
        tips = {billing.SIMPLE: "簡單：小計 = 單價 × 數量",
                billing.MANUAL: "計費數量可自行填寫",
                billing.WEIGHTED: "委託數量與計費數量由加權明細自動計算"}
        self.billable_input.setToolTip(tips[mode])

    def _refresh(self, *_):
        mode = self.mode()
        if mode == billing.WEIGHTED and self.weighting:
            for box, value in ((self.qty_input, billing.weighted_source_quantity(self.weighting)),
                               (self.billable_input, billing.weighted_quantity(self.weighting))):
                box.blockSignals(True)
                box.setValue(value)
                box.blockSignals(False)
        elif mode == billing.SIMPLE:
            self.billable_input.blockSignals(True)
            self.billable_input.setValue(self.qty_input.value())
            self.billable_input.blockSignals(False)
        self._last_qty = self.qty_input.value()
        self.subtotal_label.setText(billing.format_number(billing.item_subtotal(self.to_item())))
        self._emit_changed()


class WeightingDialog(QDialog):
    """加權明細：每個級距的數量 × 計費比例。"""

    def __init__(self, profiles: List[dict], weighting: Optional[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("加權明細")
        self.setMinimumSize(560, 420)
        self.profiles = profiles
        self._custom = None

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("加權表:"))
        self.profile_input = QComboBox()
        for p in profiles:
            self.profile_input.addItem(p.get("name", ""), p.get("id"))
        top.addWidget(self.profile_input, 1)
        layout.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["級距", "數量", "計費比例 (%)", "計費數量"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.table, 1)

        self.round_input = QCheckBox("計費數量四捨五入到整數")
        self.round_input.toggled.connect(self._refresh_totals)
        layout.addWidget(self.round_input)
        self.total_label = QLabel()
        self.total_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.total_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("確定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if weighting:
            index = self.profile_input.findData(weighting.get("profile_id"))
            if index < 0:
                self.profile_input.addItem(weighting.get("profile_name") or "（任務自訂）", weighting.get("profile_id"))
                index = self.profile_input.count() - 1
            self.profile_input.setCurrentIndex(index)
            self._load(weighting)
        elif profiles:
            self._load(billing.weighting_from_profile(profiles[0]))
        self.profile_input.currentIndexChanged.connect(self._on_profile_changed)

    def _load(self, weighting: dict):
        self.round_input.setChecked(bool(weighting.get("round_to_integer", True)))
        self.table.setRowCount(0)
        for band in weighting.get("bands", []):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(band.get("label", "")))
            count = number_box()
            count.setValue(float(band.get("count", 0) or 0))
            rate = number_box(decimals=1, maximum=1000)
            rate.setValue(float(band.get("rate", 1) or 0) * 100)
            for box in (count, rate):
                box.valueChanged.connect(self._refresh_totals)
            self.table.setCellWidget(row, 1, count)
            self.table.setCellWidget(row, 2, rate)
            result = QTableWidgetItem("0")
            result.setFlags(Qt.ItemIsEnabled)
            result.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 3, result)
        self._refresh_totals()

    def _on_profile_changed(self, _index):
        profile = billing.find_profile(self.profiles, self.profile_input.currentData())
        if profile is None:
            return
        counts = {b["label"]: b["count"] for b in self.weighting()["bands"]}
        self._load(billing.weighting_from_profile(profile, counts))

    def weighting(self) -> dict:
        bands = []
        for row in range(self.table.rowCount()):
            label_item = self.table.item(row, 0)
            bands.append({"label": label_item.text() if label_item else "",
                          "rate": round(self.table.cellWidget(row, 2).value() / 100, 4),
                          "count": self.table.cellWidget(row, 1).value()})
        return {"profile_id": self.profile_input.currentData() or "",
                "profile_name": self.profile_input.currentText(),
                "round_to_integer": self.round_input.isChecked(),
                "bands": bands}

    def _refresh_totals(self, *_):
        weighting = self.weighting()
        for row, band in enumerate(weighting["bands"]):
            item = self.table.item(row, 3)
            if item:
                item.setText(billing.format_number(band["count"] * band["rate"]))
        source = billing.weighted_source_quantity(weighting)
        billable = billing.weighted_quantity(weighting)
        ratio = f"（{billable / source:.1%}）" if source else ""
        self.total_label.setText(f"委託 {billing.format_number(source)} → 計費 {billing.format_number(billable)}{ratio}")


class PaymentRuleEditor(QWidget):
    """編輯結算與收款規則，下方附一行範例預覽。"""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setRowWrapPolicy(QFormLayout.WrapLongRows)  # 窄的時候標題移到上方
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.setVerticalSpacing(10)

        def flow(*widgets):
            """放不下時自動換行的一列。"""
            holder = QWidget()
            row = FlowLayout(holder, spacing=6)
            for w in widgets:
                row.addWidget(w)
            return holder

        self.settlement_months = QComboBox()
        for months, text in payment_terms.SETTLEMENT_MONTHS:
            self.settlement_months.addItem(text, months)
        self.settlement_months.setToolTip("例如「當月委託交件、次月結算、再次月付款」，就選「交件次月」，收款日選「結算後第 1 個月」")
        self.settlement_day = QComboBox()
        self.settlement_day.addItem("月底", 0)
        for d in range(1, 32):
            self.settlement_day.addItem(f"{d} 日", d)
        self.settlement_weekend = self._weekend_box()
        layout.addRow("結算日", flow(self.settlement_months, self.settlement_day, QLabel("結算，遇假日"),
                                     self.settlement_weekend))

        self.payment_type = QComboBox()
        self.payment_type.addItem("結算後第 N 個月的某日", payment_terms.MONTH_DAY)
        self.payment_type.addItem("結算後 N 天", payment_terms.DAYS_AFTER)
        self.payment_months = QSpinBox()
        self.payment_months.setRange(0, 24)
        self.payment_months.setPrefix("第 ")
        self.payment_months.setSuffix(" 個月")
        self.payment_months.setToolTip("0 = 結算當月，1 = 次月")
        self.payment_day = QComboBox()
        self.payment_day.addItem("月底", 0)
        for d in range(1, 32):
            self.payment_day.addItem(f"{d} 日", d)
        self.payment_days = QSpinBox()
        self.payment_days.setRange(0, 730)
        self.payment_days.setSuffix(" 天")
        self.payment_weekend = self._weekend_box()
        layout.addRow("收款日", flow(self.payment_type, self.payment_months, self.payment_day, self.payment_days,
                                     QLabel("遇假日"), self.payment_weekend))

        self.calendars = []
        self.calendar_btn = QToolButton()
        self.calendar_btn.setProperty("textButton", True)
        self.calendar_btn.setPopupMode(QToolButton.InstantPopup)
        self.calendar_btn.setMenu(QMenu(self.calendar_btn))
        self.calendar_btn.setCursor(Qt.PointingHandCursor)
        self.calendar_btn.setToolTip("判斷國定假日、補假與補班日用的行事曆；沒選的話只看週六、週日")
        layout.addRow("假日依據", self.calendar_btn)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setProperty("muted", True)
        layout.addRow("", self.preview)

        for box in (self.settlement_months, self.settlement_day, self.settlement_weekend, self.payment_type,
                    self.payment_day, self.payment_weekend):
            box.currentIndexChanged.connect(self._on_changed)
        for box in (self.payment_months, self.payment_days):
            box.valueChanged.connect(self._on_changed)
        self.set_rule(payment_terms.DEFAULT_RULE)

    @staticmethod
    def _weekend_box():
        box = QComboBox()
        for key, label in payment_terms.WEEKEND_OPTIONS:
            box.addItem(label, key)
        return box

    def set_calendars(self, calendars):
        """設定可選的假日行事曆，保留目前勾選的項目。"""
        selected = self._selected_calendar_ids()
        self.calendars = calendars
        self._build_calendar_menu(selected)
        self._update_state()

    def _selected_calendar_ids(self):
        return [a.data() for a in self.calendar_btn.menu().actions() if a.isCheckable() and a.isChecked()]

    def _build_calendar_menu(self, selected):
        menu = self.calendar_btn.menu()
        menu.clear()
        for c in self.calendars:
            action = menu.addAction(c.get("name", ""))
            action.setCheckable(True)
            action.setData(c.get("id"))
            action.setChecked(c.get("id") in selected)
            action.toggled.connect(self._on_changed)
        if not self.calendars:
            menu.addAction("還沒有假日行事曆").setEnabled(False)

    def set_rule(self, rule):
        rule = payment_terms.normalize_rule(rule)
        self.calendar_btn.menu().blockSignals(True)
        self._build_calendar_menu(rule["calendar_ids"])
        self.calendar_btn.menu().blockSignals(False)
        widgets = (self.settlement_months, self.settlement_day, self.settlement_weekend, self.payment_type,
                   self.payment_day, self.payment_weekend, self.payment_months, self.payment_days)
        for w in widgets:
            w.blockSignals(True)
        for box, key in ((self.settlement_months, "settlement_months"), (self.settlement_day, "settlement_day"), (self.settlement_weekend, "settlement_weekend"),
                         (self.payment_type, "payment_type"), (self.payment_day, "payment_day"),
                         (self.payment_weekend, "payment_weekend")):
            box.setCurrentIndex(max(0, box.findData(rule[key])))
        self.payment_months.setValue(rule["payment_months"])
        self.payment_days.setValue(rule["payment_days"])
        for w in widgets:
            w.blockSignals(False)
        self._update_state()

    def rule(self) -> dict:
        return payment_terms.normalize_rule({
            "settlement_months": self.settlement_months.currentData(),
            "settlement_day": self.settlement_day.currentData(),
            "settlement_weekend": self.settlement_weekend.currentData(),
            "payment_type": self.payment_type.currentData(),
            "payment_months": self.payment_months.value(),
            "payment_day": self.payment_day.currentData(),
            "payment_days": self.payment_days.value(),
            "payment_weekend": self.payment_weekend.currentData(),
            "calendar_ids": self._selected_calendar_ids(),
        })

    def _on_changed(self, *_):
        self._update_state()
        self.changed.emit()

    def _update_state(self):
        by_days = self.payment_type.currentData() == payment_terms.DAYS_AFTER
        self.payment_months.setVisible(not by_days)
        self.payment_day.setVisible(not by_days)
        self.payment_days.setVisible(by_days)
        rule = self.rule()
        names = [c.get("name", "") for c in self.calendars if c.get("id") in rule["calendar_ids"]]
        self.calendar_btn.setText(("、".join(names) if names else "只看週六、週日") + "  ▾")
        today = date.today().isoformat()
        settled, paid = payment_terms.compute_dates(today, rule, holidays.make_is_off(self.calendars, rule["calendar_ids"]))
        fmt = lambda s: f"{int(s[5:7])}/{int(s[8:10])}"
        self.preview.setText(f"{payment_terms.describe_rule(rule)}\n例：今天（{fmt(today)}）交件 → "
                             f"{fmt(settled)} 結算 → {fmt(paid)} 收款")
