from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, icon, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        if icon:
            self.setIcon(icon)
        self.setToolTip("CocoTimer")
        self.menu = QMenu()
        show_action = QAction("顯示主視窗", self)
        show_action.triggered.connect(self.show_main_window)
        self.dock_action = QAction("側邊停靠模式", self)
        self.dock_action.setCheckable(True)
        self.dock_action.toggled.connect(self.set_dock)
        quit_action = QAction("結束程式", self)
        quit_action.triggered.connect(self.quit_application)
        self.menu.addAction(show_action)
        self.menu.addAction(self.dock_action)
        self.menu.addSeparator()
        self.menu.addAction(quit_action)
        self.menu.aboutToShow.connect(self._sync_menu)
        self.setContextMenu(self.menu)
        self.activated.connect(self.on_tray_icon_activated)

    def show_main_window(self):
        if self.main_window:
            self.main_window.restore_from_tray()

    def _sync_menu(self):
        if self.main_window:
            self.dock_action.blockSignals(True)
            self.dock_action.setChecked(self.main_window.dock.active)
            self.dock_action.blockSignals(False)

    def set_dock(self, on):
        if self.main_window:
            self.main_window.set_dock_enabled(on)

    def quit_application(self):
        if self.main_window:
            self.main_window.quit_app()
        else:
            QApplication.instance().quit()

    def on_tray_icon_activated(self, reason):
        if not self.main_window:
            return
        if reason == QSystemTrayIcon.Trigger:
            # 單擊：視窗在前面就收起來，否則叫出來
            window = self.main_window
            if window.dock.active:
                window.dock.toggle()
                return
            if window.isVisible() and not window.isMinimized() and window.isActiveWindow():
                if window.settings.minimize_to_tray:
                    window.hide()
                else:
                    window.showMinimized()
            else:
                window.restore_from_tray()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.main_window.restore_from_tray()
