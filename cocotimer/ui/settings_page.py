"""設定頁：一般、提醒、番茄鐘、懸浮工具、側邊停靠、任務、外觀、資料，全部在同一頁。

改了就生效（不需要按「儲存」）。數字類的選項會稍等一下再寫檔，避免連按時一直存。
"""
import json
import os
import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QFontDialog, QFrame, QGridLayout,
                               QHBoxLayout, QKeySequenceEdit, QLabel, QMessageBox, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

from cocotimer import AUTHOR_URL, SITE_URL, __version__, sounds
from cocotimer import tasks as tasks_service
from cocotimer import theme as theme_module
from cocotimer.models import Settings, ThemeConfig
from cocotimer.paths import DATA_DIR
from cocotimer.startup import is_startup_enabled, set_startup
from cocotimer.ui.dock import find_screen, screen_label
from cocotimer.ui.task_dialog import CURRENCIES
from cocotimer.ui.widgets import FlowLayout, button, label, section

COLORS = [("背景", "bg_color"), ("文字", "text_color"), ("卡片底色", "surface_color"), ("側邊欄", "sidebar_color"),
          ("強調色", "accent_color"), ("強調色上的文字", "accent_text_color"), ("次要文字", "muted_color"),
          ("邊框", "border_color"), ("按鈕", "btn_color"), ("按鈕懸停", "btn_hover"), ("週末與假日", "weekend_color"),
          ("非本月日期", "other_month_color"), ("行程高亮", "event_highlight_color")]


def _hint(text):
    lab = label(text, muted=True, wrap=True)
    return lab


def _shrinkable(combo):
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(6)
    return combo


def _spin(minimum, maximum, suffix, step=1):
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setSuffix(suffix)
    box.setSingleStep(step)
    return box


class SettingsPage(QScrollArea):
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
        self.root.setSpacing(14)
        self._pending = {}
        self._loading = False
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(350)
        self.save_timer.timeout.connect(self._flush)
        self.color_buttons = {}
        self._build()
        self.reload()
        self.set_hotkey_status(getattr(main_window, "hotkey_status", ""))

    # --- 版面 ---

    def _build(self):
        title = QLabel("設定")
        title.setObjectName("pageTitle")
        self.root.addWidget(title)
        self.root.addWidget(_hint("改了就會生效，不需要按儲存。"))

        # 一般
        card, v = section("一般")
        self.cb_startup = QCheckBox("開機時自動啟動")
        self.cb_startup.setEnabled(sys.platform == "win32")
        self.cb_startup.toggled.connect(self._toggle_startup)
        self.cb_tray = QCheckBox("最小化時縮到系統匣")
        self.cb_tray.toggled.connect(lambda on: self._change(minimize_to_tray=on))
        v.addWidget(self.cb_startup)
        v.addWidget(_hint("僅限 Windows。"))
        v.addWidget(self.cb_tray)
        v.addWidget(_hint("取消勾選的話，最小化時會留在工作列。"))
        self.root.addWidget(card)

        # 提醒與聲音
        card, grid = section("提醒與聲音", QGridLayout)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.cb_water = QCheckBox("喝水提醒")
        self.cb_water.toggled.connect(lambda on: self._change(water_reminder_enabled=on))
        self.spin_water = _spin(1, 480, " 分鐘")
        self.spin_water.valueChanged.connect(lambda v: self._change(water_reminder_interval=v))
        self.cb_sound = QCheckBox("提醒時播放聲音")
        self.cb_sound.toggled.connect(lambda on: self._change(sound_enabled=on))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume_label = label("", role="mono", muted=True)
        self.volume_label.setMinimumWidth(44)
        self.volume.valueChanged.connect(self._volume_changed)
        grid.addWidget(self.cb_water, 0, 0, 1, 3)
        grid.addWidget(QLabel("每隔"), 1, 0)
        grid.addWidget(self.spin_water, 1, 1, 1, 2)
        grid.addWidget(self.cb_sound, 2, 0, 1, 3)
        grid.addWidget(QLabel("音量"), 3, 0)
        grid.addWidget(self.volume, 3, 1)
        grid.addWidget(self.volume_label, 3, 2)
        self.sound_labels = {}
        row = 4
        for kind, (name, _default, _field) in sounds.KINDS.items():
            box = QVBoxLayout()
            box.setSpacing(4)
            title = QLabel(f"{name}的聲音")
            current = label("", muted=True, wrap=True)
            self.sound_labels[kind] = current
            box.addWidget(title)
            box.addWidget(current)
            box.addWidget(self._button_flow((("選擇音效…", lambda k=kind: self._choose_sound(k)),
                                             ("試聽", lambda k=kind: self.mw.sounds.play(k)),
                                             ("還原", lambda k=kind: self._set_sound(k, "")))))
            grid.addLayout(box, row, 0, 1, 3)
            row += 1
        grid.addWidget(_hint("可以換成自己的 WAV 音效檔（30 秒以內）；「還原」改回內建音效。"
                             "選好的檔案會複製到資料夾裡，帶著走也不會不見。"),
                       row, 0, 1, 3)
        self.root.addWidget(card)

        # 番茄鐘
        card, grid = section("番茄鐘", QGridLayout)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.spin_work = _spin(1, 480, " 分鐘")
        self.spin_work.valueChanged.connect(lambda v: self._change(pomodoro_work_minutes=v))
        self.spin_break = _spin(1, 480, " 分鐘")
        self.spin_break.valueChanged.connect(lambda v: self._change(pomodoro_break_minutes=v))
        grid.addWidget(QLabel("專注"), 0, 0)
        grid.addWidget(self.spin_work, 0, 1)
        grid.addWidget(QLabel("休息"), 1, 0)
        grid.addWidget(self.spin_break, 1, 1)
        grid.addWidget(_hint("在「今天」頁可以選擇要專注的任務，專注時間會記到那個任務上。"), 2, 0, 1, 2)
        self.root.addWidget(card)

        # 懸浮工具
        card, v = section("懸浮工具")
        self.cb_topmost = QCheckBox("保持在最上層")
        self.cb_topmost.toggled.connect(lambda on: self._change(keep_floats_on_top=on))
        self.cb_float_lock = QCheckBox("鎖定位置")
        self.cb_float_lock.toggled.connect(lambda on: self._float_option(floats_locked=on))
        self.cb_float_dark = QCheckBox("深色外觀")
        self.cb_float_dark.toggled.connect(lambda on: self._float_option(floats_dark=on))
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("背景不透明度"))
        self.float_opacity = QSlider(Qt.Horizontal)
        self.float_opacity.setRange(20, 100)
        self.float_opacity_label = label("", role="mono", muted=True)
        self.float_opacity_label.setMinimumWidth(44)
        self.float_opacity.valueChanged.connect(self._opacity_changed)
        opacity_row.addWidget(self.float_opacity, 1)
        opacity_row.addWidget(self.float_opacity_label)
        v.addWidget(self.cb_topmost)
        v.addWidget(_hint("切換視窗時，讓懸浮工具自動回到最上層（僅限 Windows）。"))
        v.addWidget(self.cb_float_lock)
        v.addWidget(self.cb_float_dark)
        v.addLayout(opacity_row)
        self.root.addWidget(card)

        # 側邊停靠與快捷鍵
        card, v = section("側邊停靠與快捷鍵")
        self.cb_dock = QCheckBox("側邊停靠模式")
        self.cb_dock.toggled.connect(lambda on: self._change(dock_enabled=on))
        v.addWidget(self.cb_dock)
        v.addWidget(_hint("主視窗收進螢幕邊緣的小把手，點一下就從側邊滑出來；點到其他程式時自動收回。"))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        self.dock_side = QComboBox()
        self.dock_side.addItem("右邊", "right")
        self.dock_side.addItem("左邊", "left")
        self.dock_side.currentIndexChanged.connect(lambda _i: self._change(dock_side=self.dock_side.currentData()))
        self.dock_screen = _shrinkable(QComboBox())
        self.dock_screen.currentIndexChanged.connect(
            lambda _i: self._change(dock_screen=self.dock_screen.currentData() or ""))
        self.dock_width = _spin(15, 60, " %", 1)
        self.dock_width.setToolTip("螢幕寬度的百分比（至少 420 px）")
        self.dock_width.valueChanged.connect(lambda val: self._change(dock_width_percent=val))
        grid.addWidget(QLabel("停在"), 0, 0)
        grid.addWidget(self.dock_side, 0, 1)
        grid.addWidget(QLabel("螢幕"), 1, 0)
        grid.addWidget(self.dock_screen, 1, 1)
        grid.addWidget(QLabel("寬度"), 2, 0)
        grid.addWidget(self.dock_width, 2, 1)
        v.addLayout(grid)
        self.cb_dock_hover = QCheckBox("滑鼠停在把手上就展開")
        self.cb_dock_hover.toggled.connect(lambda on: self._change(dock_open_on_hover=on))
        v.addWidget(self.cb_dock_hover)
        v.addSpacing(6)
        self.cb_hotkey = QCheckBox("全域快捷鍵")
        self.cb_hotkey.toggled.connect(lambda on: self._change(hotkey_enabled=on))
        self.hotkey_edit = QKeySequenceEdit()
        if hasattr(self.hotkey_edit, "setMaximumSequenceLength"):
            self.hotkey_edit.setMaximumSequenceLength(1)
        if hasattr(self.hotkey_edit, "setClearButtonEnabled"):
            self.hotkey_edit.setClearButtonEnabled(True)
        self.hotkey_edit.editingFinished.connect(self._hotkey_edited)
        v.addWidget(self.cb_hotkey)
        v.addWidget(self.hotkey_edit)
        v.addWidget(_hint("在任何程式裡按下就能叫出或收起 CocoTimer（停靠模式時是展開／收回側欄）。僅限 Windows。"))
        self.hotkey_status = _hint("")
        self.hotkey_status.setVisible(False)
        v.addWidget(self.hotkey_status)
        self.root.addWidget(card)

        # 任務
        card, grid = section("任務", QGridLayout)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.currency_input = _shrinkable(QComboBox())
        self.currency_input.setEditable(True)
        self.currency_input.addItems(CURRENCIES)
        self.currency_input.currentTextChanged.connect(
            lambda text: self._change(default_currency=text.strip().upper() or "NTD"))
        self.spin_closed = _spin(1, 500, " 件")
        self.spin_closed.valueChanged.connect(lambda val: self._change(max_completed_tasks=val))
        grid.addWidget(label("常用幣別", wrap=True), 0, 0)
        grid.addWidget(self.currency_input, 0, 1)
        grid.addWidget(label("已結案顯示筆數", wrap=True), 1, 0)
        grid.addWidget(self.spin_closed, 1, 1)
        grid.addWidget(_hint("新任務和新客戶會先用常用幣別。"), 2, 0, 1, 2)
        self.root.addWidget(card)

        # 外觀
        card, v = section("外觀")
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("配色"))
        self.preset_input = _shrinkable(QComboBox())
        self.preset_input.addItem("自訂", "")
        for name in theme_module.PRESETS:
            self.preset_input.addItem(name, name)
        self.preset_input.activated.connect(self._apply_preset)
        preset_row.addWidget(self.preset_input, 1)
        v.addLayout(preset_row)
        self.color_grid = QGridLayout()
        self.color_grid.setContentsMargins(0, 0, 0, 0)
        self.color_grid.setHorizontalSpacing(10)
        self.color_grid.setVerticalSpacing(8)
        self.color_cells = []
        for text, attr in COLORS:
            btn = QPushButton()
            btn.setFixedSize(56, 28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, a=attr, t=text: self._pick_color(a, t))
            self.color_buttons[attr] = btn
            self.color_cells.append((QLabel(text), btn))
        self._color_columns = None
        v.addLayout(self.color_grid)
        font_row = QHBoxLayout()
        self.font_label = label("", wrap=True)
        font_btn = button("選擇字體…")
        font_btn.clicked.connect(self._pick_font)
        font_row.addWidget(self.font_label, 1)
        font_row.addWidget(font_btn)
        v.addLayout(font_row)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("文字大小"))
        self.font_size = _spin(9, 14, " pt")
        self.font_size.valueChanged.connect(self._font_size_changed)
        size_row.addWidget(self.font_size, 1)
        v.addLayout(size_row)
        v.addWidget(self._button_flow((("匯出配色…", self._export_theme), ("匯入配色…", self._import_theme),
                                       ("恢復預設外觀", self._reset_theme))))
        self.root.addWidget(card)

        # 資料
        card, v = section("資料")
        v.addWidget(_hint("CocoTimer 的資料都放在下面這個資料夾裡；整個程式資料夾壓縮起來就能帶著走。每天會自動備份一次。"))
        path = label(DATA_DIR, wrap=True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(path)
        v.addWidget(self._button_flow((("開啟資料夾", lambda: self._open_folder(DATA_DIR)),
                                       ("開啟備份資料夾", lambda: self._open_folder(os.path.join(DATA_DIR, "backups"))),
                                       ("假日行事曆…", self._manage_holidays))))
        self.root.addWidget(card)

        reset = button("恢復預設設定…", link=True)
        reset.setToolTip("把提醒、聲音、番茄鐘和任務的設定恢復預設（外觀、懸浮工具和側邊停靠不受影響）")
        reset.clicked.connect(self._reset_general)
        self.root.addWidget(reset, 0, Qt.AlignLeft)
        about = label(f'CocoTimer v{__version__} · <a href="{SITE_URL}">官網與使用說明</a>'
                      f' · 作者 <a href="{AUTHOR_URL}">Coco</a>', muted=True, wrap=True)
        about.setTextFormat(Qt.RichText)
        about.setOpenExternalLinks(True)
        self.root.addWidget(about)
        self.root.addStretch()

    @staticmethod
    def _button_flow(items):
        """一排按鈕，放不下時自動換行。"""
        holder = QWidget()
        flow = FlowLayout(holder, spacing=8)
        for text, slot in items:
            b = button(text)
            b.clicked.connect(slot)
            flow.addWidget(b)
        return holder

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.viewport().width()
        side = 28 if width >= 640 else 16
        side = max(side, (width - 820) // 2)  # 很寬的時候內容置中，不要拉得太長
        self.root.setContentsMargins(side, 24, side, 28)
        self._place_colors(2 if width >= 520 else 1)

    def _place_colors(self, columns):
        if columns == self._color_columns:
            return
        self._color_columns = columns
        for lab, btn in self.color_cells:
            self.color_grid.removeWidget(lab)
            self.color_grid.removeWidget(btn)
        for i, (lab, btn) in enumerate(self.color_cells):
            row, col = divmod(i, columns)
            self.color_grid.addWidget(lab, row, col * 3)
            self.color_grid.addWidget(btn, row, col * 3 + 1)
        self.color_grid.setColumnMinimumWidth(2, 24)
        self.color_grid.setColumnStretch(2, 1)

    # --- 讀取 ---

    def reload(self):
        """依目前的設定更新畫面上的選項（系統匣、把手、今天頁改了設定時也會呼叫）。"""
        self._loading = True
        s = self.data_manager.load_settings()
        self.cb_startup.setChecked(is_startup_enabled())
        self.cb_tray.setChecked(s.minimize_to_tray)
        self.cb_water.setChecked(s.water_reminder_enabled)
        self.spin_water.setValue(s.water_reminder_interval)
        self.cb_sound.setChecked(s.sound_enabled)
        self.volume.setValue(int(round(s.volume * 100)))
        self.volume_label.setText(f"{self.volume.value()}%")
        self.spin_work.setValue(s.pomodoro_work_minutes)
        self.spin_break.setValue(s.pomodoro_break_minutes)
        self.cb_topmost.setChecked(s.keep_floats_on_top)
        self.cb_float_lock.setChecked(s.floats_locked)
        self.cb_float_dark.setChecked(s.floats_dark)
        self.float_opacity.setValue(s.floats_opacity)
        self.float_opacity_label.setText(f"{s.floats_opacity}%")
        self.cb_dock.setChecked(s.dock_enabled)
        self.dock_side.setCurrentIndex(max(0, self.dock_side.findData(s.dock_side)))
        self.dock_screen.clear()
        current = find_screen(s.dock_screen)
        for i, screen in enumerate(QGuiApplication.screens()):
            self.dock_screen.addItem(screen_label(i, screen), screen.name())
            if screen == current:
                self.dock_screen.setCurrentIndex(i)
        self.dock_width.setValue(s.dock_width_percent)
        self.cb_dock_hover.setChecked(s.dock_open_on_hover)
        self.cb_hotkey.setChecked(s.hotkey_enabled)
        self.hotkey_edit.setKeySequence(QKeySequence(s.hotkey))
        self.spin_closed.setValue(s.max_completed_tasks)
        self.currency_input.setCurrentText(s.default_currency or "NTD")
        for kind, (_name, _default, field) in sounds.KINDS.items():
            custom = getattr(s, field, "")
            exists = custom and os.path.isfile(os.path.join(sounds.custom_dir(self.data_manager.data_dir), custom))
            self.sound_labels[kind].setText(f"目前：{custom.split('_', 1)[-1]}" if exists else "目前：內建音效")
        self._load_theme(s.theme)
        self._loading = False

    load_dock_settings = reload  # 舊名稱

    def _load_theme(self, theme):
        for attr, btn in self.color_buttons.items():
            color = getattr(theme, attr)
            btn.setStyleSheet(f"QPushButton {{ background: {color}; border: 1px solid rgba(0,0,0,0.25); border-radius: 8px; }}")
            btn.setToolTip(color)
        match = next((name for name, colors in theme_module.PRESETS.items()
                      if all(getattr(theme, k, None) == v for k, v in colors.items())), "")
        self.preset_input.setCurrentIndex(max(0, self.preset_input.findData(match)))
        styles = [n for n, on in (("粗體", theme.font_bold), ("斜體", theme.font_italic)) if on]
        self.font_label.setText(f"字體：{theme.font_family}" + (f"（{'、'.join(styles)}）" if styles else ""))
        self.font_size.setValue(int(getattr(theme, "base_font_size", 10)))

    def set_hotkey_status(self, text):
        self.hotkey_status.setText(text)
        self.hotkey_status.setVisible(bool(text))

    # --- 寫入 ---

    def _change(self, **changes):
        if self._loading:
            return
        self._pending.update(changes)
        self.save_timer.start()

    def _flush(self):
        if not self._pending:
            return
        changes, self._pending = self._pending, {}
        self.mw.update_settings(**changes)
        self.mw._on_settings_saved()

    def flush(self):
        """離開頁面或關閉程式前，把還沒寫入的變更存起來。"""
        self.save_timer.stop()
        self._flush()

    def _volume_changed(self, value):
        self.volume_label.setText(f"{value}%")
        self._change(volume=value / 100)

    def _opacity_changed(self, value):
        self.float_opacity_label.setText(f"{value}%")
        if not self._loading:
            self._float_option(floats_opacity=value)

    def _float_option(self, **changes):
        if not self._loading:
            self.mw.set_floats_option(**changes)

    def _toggle_startup(self, on):
        if self._loading:
            return
        if not set_startup(on):
            QMessageBox.warning(self, "開機自動啟動", "無法修改開機啟動設定（可能需要系統權限）。")
            self._loading = True
            self.cb_startup.setChecked(is_startup_enabled())
            self._loading = False

    def _hotkey_edited(self):
        text = self.hotkey_edit.keySequence().toString(QKeySequence.PortableText)
        if text:
            self._change(hotkey=text)

    # --- 提醒音 ---

    def _choose_sound(self, kind):
        path, _ = QFileDialog.getOpenFileName(self, f"選擇{sounds.KINDS[kind][0]}的音效", "", "WAV 音效檔 (*.wav)")
        if not path:
            return
        problem = sounds.check_wav(path)
        if problem:
            QMessageBox.warning(self, "無法使用這個音效", problem)
            return
        try:
            name = sounds.import_sound(kind, path, self.data_manager.data_dir)
        except OSError as e:
            QMessageBox.warning(self, "無法使用這個音效", f"複製檔案失敗：{e}")
            return
        self._set_sound(kind, name)
        self.mw.sounds.play(kind)

    def _set_sound(self, kind, name):
        field = sounds.KINDS[kind][2]
        self.mw.update_settings(**{field: name})
        settings = self.data_manager.load_settings()
        sounds.remove_unused([getattr(settings, f) for _n, _d, f in sounds.KINDS.values()], self.data_manager.data_dir)
        self.mw.sounds.reload()
        self.reload()

    # --- 外觀 ---

    def _save_theme(self, theme):
        settings = self.data_manager.load_settings()
        settings.theme = theme
        self.data_manager.save_settings(settings)
        self.mw.apply_theme_globally()
        self._loading = True
        self._load_theme(theme)
        self._loading = False

    def _current_theme(self):
        return self.data_manager.load_settings().theme

    def _apply_preset(self, _index):
        name = self.preset_input.currentData()
        if not name:
            return
        theme = self._current_theme()
        for key, value in theme_module.PRESETS[name].items():
            setattr(theme, key, value)
        self._save_theme(theme)

    def _pick_color(self, attr, text):
        theme = self._current_theme()
        color = QColorDialog.getColor(QColor(getattr(theme, attr)), self, f"選擇{text}的顏色")
        if color.isValid():
            setattr(theme, attr, color.name().upper())
            self._save_theme(theme)

    def _pick_font(self):
        theme = self._current_theme()
        current = QFont(theme.font_family)
        current.setBold(theme.font_bold)
        current.setItalic(theme.font_italic)
        ok, font = QFontDialog.getFont(current, self, "選擇字體")
        if ok:
            theme.font_family = font.family()
            theme.font_bold = font.bold()
            theme.font_italic = font.italic()
            theme.font_underline = font.underline()
            theme.font_strikeout = font.strikeOut()
            theme.font_weight = int(font.weight())
            self._save_theme(theme)

    def _font_size_changed(self, value):
        if self._loading:
            return
        theme = self._current_theme()
        if theme.base_font_size != value:
            theme.base_font_size = value
            self._save_theme(theme)

    def _export_theme(self):
        path, _ = QFileDialog.getSaveFileName(self, "匯出配色", "CocoTimer 配色.json", "JSON 檔案 (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._current_theme().to_dict(), f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "匯出配色", "配色已匯出。")

    def _import_theme(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入配色", "", "JSON 檔案 (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("檔案內容不是配色")
            self._save_theme(ThemeConfig.from_dict(data))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "匯入配色", f"匯入失敗：{e}")

    def _reset_theme(self):
        if QMessageBox.question(self, "恢復預設外觀", "要把配色、字體和文字大小恢復成預設值嗎？") == QMessageBox.Yes:
            self._save_theme(ThemeConfig())

    # --- 資料 ---

    def _open_folder(self, path):
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _manage_holidays(self):
        from cocotimer.ui.holidays_dialog import HolidayCalendarsDialog
        dialog = HolidayCalendarsDialog(self.data_manager.load_holidays(), self)
        if not dialog.exec():
            return
        calendars = dialog.result_calendars()
        self.data_manager.save_holidays(calendars)
        tasks = self.data_manager.load_tasks()
        if tasks_service.recompute_billing_dates(tasks, self.data_manager.load_clients(),
                                                 self.data_manager.load_billing(), calendars):
            self.data_manager.save_tasks(tasks)
        self.mw.task_page.tasks = self.data_manager.load_tasks()
        self.mw.task_page.update_task_list()
        self.mw.refresh_tasks()

    def _reset_general(self):
        if QMessageBox.question(self, "恢復預設", "要把提醒、聲音、番茄鐘和任務的設定恢復成預設值嗎？\n"
                                                  "（外觀、懸浮工具和側邊停靠不受影響）") != QMessageBox.Yes:
            return
        d = Settings()
        self.mw.update_settings(water_reminder_enabled=d.water_reminder_enabled,
                                water_reminder_interval=d.water_reminder_interval, sound_enabled=d.sound_enabled,
                                volume=d.volume, pomodoro_work_minutes=d.pomodoro_work_minutes,
                                pomodoro_break_minutes=d.pomodoro_break_minutes,
                                max_completed_tasks=d.max_completed_tasks)
        self.mw._on_settings_saved()
        self.reload()
