"""第一次開啟時的歡迎引導：三個步驟，設定常用幣別、結算方式、配色和幾個常用開關。

隨時可以按「略過」，之後在「設定」和「客戶與範本」都能再改。
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QStackedWidget, QVBoxLayout, QWidget)

from cocotimer import theme as theme_module
from cocotimer.startup import set_startup
from cocotimer.ui.billing_widgets import PaymentRuleEditor
from cocotimer.ui.task_dialog import CURRENCIES
from cocotimer.ui.widgets import button, card, label

# 配色選項：（顯示名稱, theme.PRESETS 裡的名稱）
THEMES = [("奶茶", "v3 奶茶（預設）"), ("經典", "v2 經典"), ("可可深色", "可可深色")]


class _ThemeChoice(QFrame):
    """一個配色選項：小色票加名稱，點一下選取。"""

    def __init__(self, text, preset, on_pick):
        super().__init__()
        self.preset = preset
        self.on_pick = on_pick
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("card", True)
        self.setMinimumHeight(96)
        colors = theme_module.PRESETS[preset]
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 10)
        v.setSpacing(8)
        swatch = QFrame()
        swatch.setFixedHeight(40)
        swatch.setStyleSheet(
            f"QFrame {{ border-radius: 8px; border: 1px solid {colors['border_color']};"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {colors['bg_color']},"
            f" stop:0.55 {colors['surface_color']}, stop:0.56 {colors['accent_color']}, stop:1 {colors['accent_color']}); }}")
        v.addWidget(swatch)
        self.name = label(text)
        self.name.setAlignment(Qt.AlignCenter)
        v.addWidget(self.name)

    def set_selected(self, on, accent):
        self.setStyleSheet(f"QFrame[card=\"true\"] {{ border: 2px solid {accent}; }}" if on else "")
        self.name.setStyleSheet("font-weight: 700;" if on else "")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_pick(self.preset)


class WelcomeDialog(QDialog):
    STEPS = 3

    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.data_manager = main_window.data_manager
        self.setWindowTitle("歡迎使用 CocoTimer")
        self.setMinimumSize(460, 560)
        self.resize(620, 640)
        settings = self.data_manager.load_settings()
        self.preset = next((p for _t, p in THEMES if all(getattr(settings.theme, k, None) == v
                                                          for k, v in theme_module.PRESETS[p].items())),
                           theme_module.DEFAULT_PRESET)
        self._build(settings)
        self._go(0)

    # --- 版面 ---

    def _build(self, settings):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        content = QWidget()
        content.setObjectName("contentArea")
        body = QVBoxLayout(content)
        body.setContentsMargins(28, 24, 28, 20)
        body.setSpacing(14)
        self.step_label = label("", muted=True)
        body.addWidget(self.step_label)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_hello())
        self.stack.addWidget(self._page_work(settings))
        self.stack.addWidget(self._page_look(settings))
        body.addWidget(self.stack, 1)
        layout.addWidget(content, 1)

        footer = QFrame()
        footer.setProperty("card", True)
        footer.setStyleSheet("QFrame { border-radius: 0; border-left: none; border-right: none; border-bottom: none; }")
        row = QHBoxLayout(footer)
        row.setContentsMargins(20, 12, 20, 12)
        self.skip_btn = button("略過", link=True)
        self.skip_btn.setToolTip("之後都可以在「設定」裡調整")
        self.skip_btn.clicked.connect(self._skip)
        row.addWidget(self.skip_btn)
        row.addStretch()
        self.back_btn = button("上一步")
        self.back_btn.setMinimumWidth(96)
        self.back_btn.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.next_btn = button("下一步", primary=True)
        self.next_btn.setMinimumWidth(110)
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self._next)
        row.addWidget(self.back_btn)
        row.addWidget(self.next_btn)
        layout.addWidget(footer)

    def _page(self, title, subtitle):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)
        head = QLabel(title)
        head.setObjectName("pageTitle")
        head.setWordWrap(True)
        v.addWidget(head)
        if subtitle:
            v.addWidget(label(subtitle, muted=True, wrap=True))
        return page, v

    def _page_hello(self):
        page, v = self._page("歡迎使用 CocoTimer", "給接案者的工作小幫手。先花一分鐘設定幾件事，之後隨時都能改。")
        logo = QLabel("C")
        logo.setObjectName("appLogo")
        logo.setFixedSize(56, 56)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("font-size: 26px; border-radius: 16px;")
        v.insertWidget(0, logo)
        c = card(spacing=10)
        for title, text in (("行事曆與任務", "行程、交件日和預計收款日都排在同一個行事曆上。"),
                            ("收款", "記下單價和數量，自動算出金額、結算日和收款日。"),
                            ("專注與打卡", "番茄鐘可以綁定任務，記錄每件案子花了多少時間。")):
            item = QVBoxLayout()
            item.setSpacing(2)
            t = label(title)
            t.setStyleSheet("font-weight: 700;")
            item.addWidget(t)
            item.addWidget(label(text, muted=True, wrap=True))
            c.layout().addLayout(item)
        v.addWidget(c)
        note = card(spacing=4)
        t = label("資料放在哪裡")
        t.setStyleSheet("font-weight: 700;")
        note.layout().addWidget(t)
        note.layout().addWidget(label("所有資料都存在程式旁邊的 timemanager_data 資料夾。"
                                      "換電腦時，把整個 CocoTimer 資料夾一起帶走就好。", muted=True, wrap=True))
        v.addWidget(note)
        v.addStretch()
        return page

    def _page_work(self, settings):
        page, v = self._page("接案設定", "新任務會先用這些設定，每位客戶也可以在「客戶與範本」另外設定。")
        c = card(spacing=12)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(label("常用幣別"))
        self.currency_input = QComboBox()
        self.currency_input.setEditable(True)
        self.currency_input.addItems(CURRENCIES)
        self.currency_input.setCurrentText(settings.default_currency or "NTD")
        row.addWidget(self.currency_input, 1)
        c.layout().addLayout(row)
        v.addWidget(c)
        c = card(spacing=10)
        t = label("結算與收款", role="h2")
        c.layout().addWidget(t)
        self.rule_editor = PaymentRuleEditor()
        self.rule_editor.set_calendars(self.data_manager.load_holidays())
        self.rule_editor.set_rule(self.data_manager.load_billing().payment_rule)
        c.layout().addWidget(self.rule_editor)
        v.addWidget(c)
        v.addStretch()
        return page

    def _page_look(self, settings):
        page, v = self._page("外觀與提醒", "選好就會套用，可以直接看看效果。")
        c = card(spacing=10)
        c.layout().addWidget(label("配色", role="h2"))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.theme_choices = []
        for i, (text, preset) in enumerate(THEMES):
            choice = _ThemeChoice(text, preset, self._pick_theme)
            self.theme_choices.append(choice)
            grid.addWidget(choice, 0, i)
            grid.setColumnStretch(i, 1)
        c.layout().addLayout(grid)
        v.addWidget(c)

        c = card(spacing=8)
        self.cb_water = QCheckBox("喝水提醒")
        self.cb_water.setChecked(settings.water_reminder_enabled)
        c.layout().addWidget(self.cb_water)
        self.cb_startup = QCheckBox("開機時自動啟動")
        self.cb_startup.setVisible(sys.platform == "win32")
        c.layout().addWidget(self.cb_startup)
        self.cb_dock = QCheckBox("側邊停靠模式")
        self.cb_dock.setChecked(settings.dock_enabled)
        c.layout().addWidget(self.cb_dock)
        c.layout().addWidget(label("主視窗收進螢幕邊緣的小把手，要用時點一下就從側邊滑出來。", muted=True, wrap=True))
        v.addWidget(c)
        v.addStretch()
        self._mark_theme()
        return page

    # --- 動作 ---

    def _go(self, index):
        index = max(0, min(self.STEPS - 1, index))
        self.stack.setCurrentIndex(index)
        self.step_label.setText(f"第 {index + 1} 步，共 {self.STEPS} 步")
        self.back_btn.setVisible(index > 0)
        self.next_btn.setText("開始使用" if index == self.STEPS - 1 else "下一步")

    def _next(self):
        if self.stack.currentIndex() < self.STEPS - 1:
            self._go(self.stack.currentIndex() + 1)
        else:
            self._finish()

    def _pick_theme(self, preset):
        self.preset = preset
        settings = self.data_manager.load_settings()
        for key, value in theme_module.PRESETS[preset].items():
            setattr(settings.theme, key, value)
        self.data_manager.save_settings(settings)
        self.mw.apply_theme_globally()
        self.mw.sync_settings_page()
        self._mark_theme()

    def _mark_theme(self):
        accent = self.mw.colors["accent"]
        for choice in self.theme_choices:
            choice.set_selected(choice.preset == self.preset, accent)

    def _finish(self):
        currency = self.currency_input.currentText().strip().upper() or "NTD"
        config = self.data_manager.load_billing()
        config.payment_rule = self.rule_editor.rule()
        self.data_manager.save_billing(config)
        self.mw.update_settings(default_currency=currency, water_reminder_enabled=self.cb_water.isChecked(),
                                welcome_done=True)
        if self.cb_startup.isVisible() and self.cb_startup.isChecked():
            set_startup(True)
        self.mw._on_settings_saved()
        dock = self.cb_dock.isChecked()
        self.accept()
        if dock != self.mw.settings.dock_enabled:
            self.mw.set_dock_enabled(dock)
        self.mw.sync_settings_page()

    def _skip(self):
        self.reject()

    def reject(self):
        self.mw.update_settings(welcome_done=True)  # 略過或關掉視窗也算看過，下次不會再出現
        super().reject()
