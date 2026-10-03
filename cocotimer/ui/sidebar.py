"""側邊欄：展開時顯示圖示與文字，收合時只剩圖示列。"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpacerItem,
                               QVBoxLayout)

from cocotimer import __version__
from cocotimer.ui.icons import icon
from cocotimer.ui.widgets import icon_button

EXPANDED_WIDTH = 220
COLLAPSED_WIDTH = 64

NAV_ITEMS = [
    ("today", "今天", "today"),
    ("events", "行事曆", "calendar"),
    ("tasks", "任務", "tasks"),
    ("clients", "客戶與範本", "clients"),
    ("work", "打卡紀錄", "work"),
    ("stats", "統計", "stats"),
    ("settings", "設定", "settings"),
]

# 停靠相關的按鈕：一般模式只顯示「停靠到螢幕邊緣」，停靠模式顯示另外三個
DOCK_ITEMS = [
    ("dock", "停靠到螢幕邊緣", "dock"),
    ("pin", "釘選（點外面不收回）", "pin"),
    ("undock", "回到一般視窗", "window"),
    ("retract", "收回", "chevron_right"),
]


class Sidebar(QFrame):
    navigate = Signal(str)
    toggle_requested = Signal()
    dock_action = Signal(str)  # dock / pin / undock / retract

    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.colors = colors
        self.collapsed = False
        self.buttons = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 16, 10, 16)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(6, 0, 0, 12)
        head.setSpacing(0)
        self.head = head
        self.logo = QLabel("C")
        self.logo.setObjectName("appLogo")
        self.logo.setFixedSize(32, 32)
        self.logo.setAlignment(Qt.AlignCenter)
        self.name = QLabel("CocoTimer")
        self.name.setObjectName("appName")
        self.toggle_btn = icon_button("collapse", colors["muted"], "收合側邊欄")
        self.toggle_btn.clicked.connect(self.toggle_requested)
        head.addWidget(self.logo)
        self.head_gap = QSpacerItem(8, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        head.addItem(self.head_gap)
        head.addWidget(self.name, 1)
        head.addWidget(self.toggle_btn)
        layout.addLayout(head)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for key, text, icon_name in NAV_ITEMS:
            btn = QPushButton(text)
            btn.setObjectName("navItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIconSize(QSize(20, 20))
            btn.setProperty("navText", text)
            btn.setProperty("iconName", icon_name)
            btn.clicked.connect(lambda _checked=False, k=key: self.navigate.emit(k))
            self.group.addButton(btn)
            self.buttons[key] = btn
            layout.addWidget(btn)
        layout.addStretch()

        self.dock_buttons = {}
        for key, text, icon_name in DOCK_ITEMS:
            btn = QPushButton(text)
            btn.setObjectName("navItem")
            btn.setCheckable(key == "pin")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIconSize(QSize(20, 20))
            btn.setProperty("navText", text)
            btn.setProperty("iconName", icon_name)
            btn.clicked.connect(lambda _checked=False, k=key: self.dock_action.emit(k))
            self.dock_buttons[key] = btn
            layout.addWidget(btn)
        self.docked = False
        self._show_dock_buttons()

        self.footer = QLabel(f"可攜模式 · 資料存放在程式資料夾\nv{__version__}")
        self.footer.setObjectName("sidebarFooter")
        self.footer.setWordWrap(True)
        layout.addWidget(self.footer)
        self.refresh_icons()

    def set_colors(self, colors):
        self.colors = colors
        self.refresh_icons()

    def refresh_icons(self):
        for key, btn in self.buttons.items():
            color = self.colors["ink"] if btn.isChecked() else self.colors["muted"]
            btn.setIcon(icon(btn.property("iconName"), color, 20))
        self.toggle_btn.setIcon(icon("collapse" if not self.collapsed else "menu", self.colors["muted"], 20))
        for key, btn in self.dock_buttons.items():
            color = self.colors["accent"] if btn.isChecked() else self.colors["muted"]
            btn.setIcon(icon(btn.property("iconName"), color, 20))

    def set_current(self, key):
        if key in self.buttons:
            self.buttons[key].setChecked(True)
        self.refresh_icons()

    def set_collapsed(self, collapsed: bool):
        self.collapsed = collapsed
        self.name.setVisible(not collapsed)
        self.logo.setVisible(not collapsed)
        self.footer.setVisible(not collapsed)
        # 收合時讓選單按鈕跟下面的圖示一樣寬，圖示才會置中
        self.head.setContentsMargins(0 if collapsed else 6, 0, 0, 12)
        self.head_gap.changeSize(0 if collapsed else 8, 0, QSizePolicy.Fixed, QSizePolicy.Minimum)
        self.toggle_btn.setSizePolicy(QSizePolicy.Expanding if collapsed else QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.toggle_btn.setFixedHeight(44 if collapsed else self.toggle_btn.sizeHint().height())
        self.head.invalidate()
        self.toggle_btn.setToolTip("展開側邊欄" if collapsed else "收合側邊欄")
        self.toggle_btn.setAccessibleName(self.toggle_btn.toolTip())
        for btn in list(self.buttons.values()) + list(self.dock_buttons.values()):
            text = btn.property("navText")
            btn.setText("" if collapsed else text)
            btn.setToolTip(text if collapsed else "")
            btn.setAccessibleName(text)
            btn.setStyleSheet("QPushButton#navItem { padding: 0; text-align: center; }" if collapsed else "")
        self.refresh_icons()

    def set_dock_mode(self, docked: bool, pinned: bool = False, side: str = "right"):
        self.docked = docked
        pin = self.dock_buttons["pin"]
        pin.setChecked(pinned)
        pin.setProperty("navText", "已釘選（點外面不收回）" if pinned else "釘選（點外面不收回）")
        self.dock_buttons["retract"].setProperty("iconName", "chevron_left" if side == "left" else "chevron_right")
        self._show_dock_buttons()
        self.set_collapsed(self.collapsed)

    def _show_dock_buttons(self):
        for key, btn in self.dock_buttons.items():
            btn.setVisible((key != "dock") == self.docked)

    def preferred_width(self) -> int:
        return COLLAPSED_WIDTH if self.collapsed else EXPANDED_WIDTH
