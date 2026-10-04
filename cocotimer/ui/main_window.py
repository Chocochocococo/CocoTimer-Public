"""主視窗：側邊欄 + 各頁面，並負責番茄鐘、提醒、懸浮工具等全程式共用的功能。"""
import sys
from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (QApplication, QGraphicsDropShadowEffect, QMainWindow, QMessageBox, QStackedWidget,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from cocotimer import tasks as tasks_service
from cocotimer import theme as theme_module
from cocotimer.data_manager import DataManager
from cocotimer.ui.calendar_page import CalendarPage
from cocotimer.ui.clients_page import ClientsPage
from cocotimer.ui.dock import DockController
from cocotimer.ui.hotkey import GlobalHotkey
from cocotimer.ui.floats import (CalendarFloat, ClockFloat, MiniBarFloat, PomodoroFloat, WeekFloat,
                                 WorkFloat)
from cocotimer.ui.pages import WorkPage
from cocotimer.ui.settings_page import SettingsPage
from cocotimer.ui.reminders import EventReminderWindow, TaskReminderWindow, ToastNotification
from cocotimer.ui.sidebar import COLLAPSED_WIDTH, EXPANDED_WIDTH, Sidebar
from cocotimer.ui.sound_player import SoundPlayer
from cocotimer.ui.stats_page import StatsPage, StatsWindow
from cocotimer.ui.tasks_page import TaskPage
from cocotimer.ui.today_page import TodayPage
from cocotimer.ui.topmost import TopmostKeeper

NARROW_WIDTH = 760  # 視窗比這個窄時，側邊欄自動變成圖示列，展開時浮在內容上方


class _Shell(QWidget):
    """主視窗的中央區域：自己排側邊欄與內容的位置。"""

    def __init__(self, on_resize):
        super().__init__()
        self._on_resize = on_resize

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._on_resize()


class _Scrim(QWidget):
    """側邊欄浮在內容上方時的半透明遮罩，點一下就收回側邊欄。"""

    def __init__(self, on_click, parent):
        super().__init__(parent)
        self._on_click = on_click
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(20, 16, 12, 0.18);")
        self.hide()

    def mousePressEvent(self, event):
        self._on_click()


class _LazyPage(QWidget):
    """先放一個空的位置，第一次需要時才建立真正的頁面。"""

    def __init__(self, factory):
        super().__init__()
        self.factory = factory
        self.page = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def ensure(self):
        if self.page is None:
            self.page = self.factory()
            self._layout.addWidget(self.page)
        return self.page


class MainWindow(QMainWindow):
    FLOAT_SPECS = {
        "clock": {"name": "數字時鐘", "icon": "clock", "cls": ClockFloat, "setting": "clock_visible"},
        "calendar": {"name": "日曆", "icon": "calendar", "cls": CalendarFloat, "setting": "calendar_visible"},
        "week": {"name": "週曆橫條", "icon": "week", "cls": WeekFloat, "setting": "week_strip_visible"},
        "pomodoro": {"name": "番茄鐘", "icon": "pomodoro", "cls": PomodoroFloat, "setting": "pomodoro_float_visible"},
        "work": {"name": "工時計時", "icon": "work", "cls": WorkFloat, "setting": "work_time_float_visible"},
        "bar": {"name": "合併迷你條", "icon": "bar", "cls": MiniBarFloat, "setting": "mini_bar_visible"},
    }

    def __init__(self, tray_icon=None):
        super().__init__()
        self.data_manager = DataManager()
        self.tray_icon = tray_icon
        self.setWindowTitle("CocoTimer")
        self.setMinimumSize(420, 560)
        self.resize(1100, 820)
        self.settings = self.data_manager.load_settings()
        self.colors = theme_module.tokens(self.settings.theme)
        self.events = self.data_manager.load_events()
        self.work_records = self.data_manager.load_work_records()
        self.floats = {key: None for key in self.FLOAT_SPECS}
        self.active_toasts = []
        self.reminder_windows = []
        self.stats_window = None  # 獨立的統計視窗（第一次開啟時才建立）
        self._overlay_open = False
        self._current_page = None
        self._quitting = False
        self._notify_key = None  # check_notifications 上次檢查時的資料版本
        self._next_notify = None  # 下一個提醒的時間

        self._setup_timers_and_sounds()
        self._build_ui()

        self.data_manager.restore_window_geometry("main_window", self)
        self.apply_theme_globally()
        self.navigate("today")
        self.update_work_status_label()
        self._restore_window_visibility()
        self.dock = DockController(self)
        self.hotkey = GlobalHotkey(self.on_hotkey)
        self._apply_hotkey()
        self.topmost = TopmostKeeper(lambda: [w for w in self.floats.values() if w and w.isVisible()] + self.dock.windows(),
                                     enabled=self.settings.keep_floats_on_top)

    def show_on_start(self):
        """程式啟動時：停靠模式就只顯示把手，否則顯示主視窗。"""
        if self.settings.dock_enabled:
            self.dock.enter()
        else:
            self.show()

    def maybe_show_welcome(self):
        """第一次使用時顯示歡迎引導；已經有資料（例如從舊版升級）就直接略過。"""
        if self.settings.welcome_done:
            return
        dm = self.data_manager
        if dm.load_tasks() or dm.load_events() or dm.load_work_records() or dm.load_clients():
            self.update_settings(welcome_done=True)
            return
        from cocotimer.ui.welcome import WelcomeDialog
        if self.dock.active:
            self.dock.slide_in()
        WelcomeDialog(self).exec()

    # --- 延後建立的頁面 ---

    @property
    def clients_page(self):
        return self._lazy["clients"].ensure()

    @property
    def stats_page(self):
        return self._lazy["stats"].ensure()

    @property
    def settings_page(self):
        return self._lazy["settings"].ensure()

    def _built(self, key):
        """已經建立的頁面（還沒打開過就是 None）。"""
        return self._lazy[key].page

    def sync_settings_page(self):
        """設定從別的地方改了（系統匣、把手選單…），設定頁已經開過的話就更新畫面。"""
        if self._built("settings"):
            self.settings_page.reload()

    # --- 舊程式碼使用的名稱 ---

    @property
    def clock_window(self):
        return self.floats["clock"]

    @property
    def calendar_window(self):
        return self.floats["calendar"]

    @property
    def pomodoro_float_window(self):
        return self.floats["pomodoro"]

    @property
    def work_time_float_window(self):
        return self.floats["work"]

    # --- 建立 ---

    def _setup_timers_and_sounds(self):
        self.notification_timer = QTimer(self)
        self.notification_timer.timeout.connect(self.check_notifications)
        self.notification_timer.start(1000)

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self._tick)
        self.tick_timer.start(1000)

        self.last_known_date = QDate.currentDate()
        self.date_check_timer = QTimer(self)
        self.date_check_timer.timeout.connect(self._check_for_date_change)
        self.date_check_timer.start(30000)

        self.water_timer = QTimer(self)
        self.water_timer.timeout.connect(self.water_reminder)
        if self.settings.water_reminder_enabled:
            self.water_timer.start(self.settings.water_reminder_interval * 60000)

        self.sounds = SoundPlayer(self.data_manager, self)

        self.pomodoro_state = "idle"  # idle / working / breaking / paused
        self.pomodoro_end_time = None
        self.pomodoro_task_id = self.settings.pomodoro_task_id  # 專注時間記到這個任務
        self._focus_started = None  # 這一段專注從什麼時候開始（還沒記進任務的部分）
        self._pomodoro_total = 0
        self._paused_phase = None
        self._paused_remaining = 0
        self._paused_total = 0
        self.pomodoro_timer = QTimer(self)
        self.pomodoro_timer.setSingleShot(True)
        self.pomodoro_timer.timeout.connect(self._update_pomodoro_timer)

    def _build_ui(self):
        self.shell = _Shell(self._layout_shell)
        self.setCentralWidget(self.shell)

        self.stack = QStackedWidget(self.shell)
        self.calendar_page = CalendarPage(self)
        self.task_page = TaskPage(self.data_manager, main_window=self)
        self.work_page = WorkPage(self.data_manager, main_window=self)
        # 不常用的頁面第一次打開時才建立，啟動比較快、平常也比較省記憶體
        self._lazy = {"clients": _LazyPage(lambda: ClientsPage(self.data_manager)),
                      "stats": _LazyPage(lambda: StatsPage(self)),
                      "settings": _LazyPage(lambda: SettingsPage(self))}
        self.today_page = TodayPage(self)  # 要在其他頁面之後建立，它會讀取打卡頁的狀態

        self.pages = {"today": self.today_page, "events": self.calendar_page, "tasks": self.task_page,
                      "clients": self._lazy["clients"], "work": self.work_page, "stats": self._lazy["stats"],
                      "settings": self._lazy["settings"]}
        for page in self.pages.values():
            self.stack.addWidget(page)

        self.scrim = _Scrim(self._close_overlay, self.shell)
        self.sidebar = Sidebar(self.colors, self.shell)
        self.sidebar.navigate.connect(self.navigate)
        self.sidebar.toggle_requested.connect(self.toggle_sidebar)
        self.sidebar.dock_action.connect(self._on_dock_action)
        # 停靠模式沒有視窗外框，在朝向螢幕內側的那一邊畫一條細線，和後面的視窗分開
        self.dock_edge = QWidget(self.shell)
        self.dock_edge.setAttribute(Qt.WA_StyledBackground, True)
        self.dock_edge.hide()

    # --- 側邊欄與頁面 ---

    def _is_narrow(self) -> bool:
        return self.shell.width() < NARROW_WIDTH

    def _layout_shell(self):
        w, h = self.shell.width(), self.shell.height()
        if self._is_narrow():
            content_x = COLLAPSED_WIDTH
            self.sidebar.set_collapsed(not self._overlay_open)
            self.sidebar.setGeometry(0, 0, EXPANDED_WIDTH if self._overlay_open else COLLAPSED_WIDTH, h)
        else:
            self._overlay_open = False
            self.sidebar.set_collapsed(self.settings.sidebar_collapsed)
            content_x = self.sidebar.preferred_width()
            self.sidebar.setGeometry(0, 0, content_x, h)
        self.stack.setGeometry(content_x, 0, max(0, w - content_x), h)
        self.scrim.setGeometry(0, 0, w, h)
        self.scrim.setVisible(self._overlay_open)
        if self._overlay_open:
            shadow = QGraphicsDropShadowEffect(self.sidebar)
            shadow.setBlurRadius(32)
            shadow.setOffset(8, 0)
            shadow.setColor(QColor(40, 30, 20, 70))
            self.sidebar.setGraphicsEffect(shadow)
        else:
            self.sidebar.setGraphicsEffect(None)
        self.scrim.raise_()
        self.sidebar.raise_()
        dock = getattr(self, "dock", None)
        docked = bool(dock and dock.active)
        self.dock_edge.setVisible(docked)
        if docked:
            self.dock_edge.setStyleSheet(f"background: {self.colors['line_strong']};")
            self.dock_edge.setGeometry(w - 1 if dock.side() == "left" else 0, 0, 1, h)
            self.dock_edge.raise_()

    def toggle_sidebar(self):
        if self._is_narrow():
            self._overlay_open = not self._overlay_open
        else:
            self.update_settings(sidebar_collapsed=not self.settings.sidebar_collapsed)
        self._layout_shell()

    def _close_overlay(self):
        if self._overlay_open:
            self._overlay_open = False
            self._layout_shell()

    def navigate(self, key):
        page = self.pages.get(key)
        if page is None:
            return
        if self._current_page == "clients" and key != "clients":
            # 離開客戶分頁時保存編輯；客戶改名或結算規則改變時任務會被更新，任務分頁要重新讀取
            if not self.clients_page.save_current(quiet=True):
                self.sidebar.set_current("clients")  # 有資料要先補（例如範本沒填名稱），留在這一頁，編輯不會不見
                return
            self.task_page.tasks = self.data_manager.load_tasks()
            self.task_page.update_task_list()
            self.refresh_tasks()
        if self._current_page == "settings" and key != "settings":
            self.settings_page.flush()
        if key == "clients":
            self.clients_page.reload(keep=self.clients_page._selected)
        elif key == "settings":
            self.settings_page.reload()
        if key == "today":
            self.today_page.refresh_all()
        elif key == "events":
            self.calendar_page.refresh()
        elif key == "stats":
            self.stats_page.refresh()
        self._current_page = key
        self.stack.setCurrentWidget(page)
        self.sidebar.set_current(key)
        self._close_overlay()

    def add_task(self):
        self.task_page.open_add_task_dialog()
        self.refresh_tasks()

    def open_task(self, task_id):
        tasks = self.task_page.tasks
        task = next((t for t in tasks if t.id == task_id), None)
        if task is None:
            self.task_page.tasks = self.data_manager.load_tasks()
            task = next((t for t in self.task_page.tasks if t.id == task_id), None)
        if task is not None:
            self.task_page.edit_task(task)
        self.refresh_tasks()

    # --- 外觀與設定 ---

    def update_settings(self, **changes):
        """重新讀取最新設定再修改，避免用舊的設定覆蓋別的頁面剛存的內容。"""
        settings = self.data_manager.load_settings()
        for key, value in changes.items():
            setattr(settings, key, value)
        self.data_manager.save_settings(settings)
        self.settings = settings

    def apply_theme_globally(self):
        """套用外觀設定到主視窗、各頁面與懸浮工具。"""
        self.settings = self.data_manager.load_settings()
        theme = self.settings.theme
        self.colors = theme_module.tokens(theme)
        font = QFont(theme.font_family)
        font.setBold(theme.font_bold)
        font.setItalic(theme.font_italic)
        font.setUnderline(theme.font_underline)
        font.setStrikeOut(theme.font_strikeout)
        QApplication.instance().setFont(font)
        palette = QApplication.instance().palette()  # 文字裡的連結用強調色
        palette.setColor(QPalette.Link, QColor(self.colors["accent"]))
        palette.setColor(QPalette.LinkVisited, QColor(self.colors["accent"]))
        QApplication.instance().setPalette(palette)
        self.setStyleSheet(theme_module.stylesheet(theme))
        self.sidebar.set_colors(self.colors)
        self.today_page.refresh_all()
        self.calendar_page.apply_colors()
        self.calendar_page.refresh()  # 行程色條依淺色／深色重畫
        self.task_page.update_task_list()
        for window in self.floats.values():
            if window is not None:
                window.update_style()
        if self._built("stats"):
            self.stats_page.apply_colors()
        if self.stats_window is not None:
            self.stats_window.apply_theme()
        self.refresh_stats()

    def _on_settings_saved(self):
        self.settings = self.data_manager.load_settings()
        if self.settings.water_reminder_enabled:
            self.water_timer.start(self.settings.water_reminder_interval * 60000)
        else:
            self.water_timer.stop()
        self.sounds.reload()
        self.task_page.max_completed_tasks = self.settings.max_completed_tasks
        self.task_page.update_task_list()
        self.topmost.set_enabled(self.settings.keep_floats_on_top)
        self.dock.apply_settings()
        self._apply_hotkey()

    # --- 側邊停靠與快捷鍵 ---

    def set_dock_enabled(self, enabled: bool):
        self.update_settings(dock_enabled=enabled)
        self.sync_settings_page()
        self.dock.apply_settings()

    def _on_dock_action(self, key):
        if key == "dock":
            self.set_dock_enabled(True)
        elif key == "undock":
            self.set_dock_enabled(False)
        elif key == "pin":
            self.dock.set_pinned(not self.dock.pinned)
        elif key == "retract":
            self.dock.slide_out()

    def _apply_hotkey(self):
        text = self.settings.hotkey
        if self.settings.hotkey_enabled:
            ok = self.hotkey.register(text)
            status = f"已啟用：{text}" if ok else (
                "目前的系統不支援全域快捷鍵" if sys.platform != "win32" else
                f"無法使用 {text}：可能被其他程式用掉了，或不是有效的組合（需要 Ctrl、Alt 或 Win 加上字母、數字或 F 鍵）")
        else:
            self.hotkey.unregister()
            status = ""
        self.hotkey_status = status
        if self._built("settings"):
            self.settings_page.set_hotkey_status(status)

    def on_hotkey(self):
        """全域快捷鍵：停靠模式時展開／收回側欄；一般模式時叫出或收起主視窗。"""
        if self.dock.active:
            self.dock.toggle()
        elif self.isVisible() and not self.isMinimized() and self.isActiveWindow():
            if self.settings.minimize_to_tray and self.tray_icon is not None:
                self.hide()
            else:
                self.showMinimized()
        else:
            self.restore_from_tray()

    # --- 懸浮工具 ---

    def float_visible(self, key) -> bool:
        window = self.floats.get(key)
        return bool(window and window.isVisible())

    def set_float_visible(self, key, visible, save=True):
        window = self.floats.get(key)
        if visible:
            if window is None:
                window = self.FLOAT_SPECS[key]["cls"](self.data_manager, controller=self)
                self.floats[key] = window
            elif hasattr(window, "refresh_events"):
                window.refresh_events()
            window.show()
            window.raise_()
            self._update_pomodoro_float_display()
            self.update_work_status_label()
        elif window is not None:
            window.hide()
        if save:
            self.update_settings(**{self.FLOAT_SPECS[key]["setting"]: visible})
        self.today_page.refresh_floats()

    def set_floats_option(self, **changes):
        """所有懸浮工具共用的選項（floats_locked、floats_dark）。"""
        self.update_settings(**changes)
        for window in self.floats.values():
            if window is not None:
                window.update_style()
        self.today_page.refresh_floats()

    def show_day(self, day):
        """從懸浮日曆雙擊某一天：叫出主視窗，切到行事曆並選取那天。"""
        self.restore_from_tray()
        self.navigate("events")
        self.calendar_page.select_day(day)

    def hide_all_floats(self):
        for key in self.FLOAT_SPECS:
            if self.float_visible(key):
                self.set_float_visible(key, False)

    def _restore_window_visibility(self):
        for key, spec in self.FLOAT_SPECS.items():
            if getattr(self.settings, spec["setting"], False):
                self.set_float_visible(key, True, save=False)

    # 舊介面的按鈕名稱（統計視窗等仍可能呼叫）
    def toggle_clock(self, save_state=True):
        self.set_float_visible("clock", not self.float_visible("clock"), save_state)

    def toggle_calendar(self, save_state=True):
        self.set_float_visible("calendar", not self.float_visible("calendar"), save_state)

    def toggle_pomodoro_float(self, save_state=True):
        self.set_float_visible("pomodoro", not self.float_visible("pomodoro"), save_state)

    def toggle_work_time_float(self, save_state=True):
        self.set_float_visible("work", not self.float_visible("work"), save_state)

    # --- 視窗行為 ---

    def restore_from_tray(self):
        """從系統匣或工具列叫出主視窗：清掉最小化狀態，顯示並移到最前面。停靠模式時改成從側邊滑出。"""
        if self.dock.active:
            self.dock.slide_in()
            return
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.windowState() & Qt.WindowMinimized and not self.dock.active:
            if self.settings.minimize_to_tray and self.tray_icon is not None and QSystemTrayIcon.isSystemTrayAvailable():
                QTimer.singleShot(0, self.hide)

    def show_toast(self, title, message):
        self.active_toasts = [t for t in self.active_toasts if t.isVisible()]
        toast = ToastNotification(title, message, self)
        screen_rect = QApplication.primaryScreen().availableGeometry()
        center_pos = screen_rect.center() - toast.rect().center()
        y_offset = sum(t.height() + 10 for t in self.active_toasts)
        toast.move(QPoint(center_pos.x(), center_pos.y() + y_offset))
        self.active_toasts.append(toast)
        toast.show()

    def save_session_state(self):
        """記錄懸浮視窗的顯示狀態與所有視窗位置（關閉程式、登出或關機時呼叫）。"""
        self._credit_focus(restart=True)  # 正在專注的話，先把到目前為止的時間記進任務
        if self._built("settings"):
            self.settings_page.flush()
        if self._current_page == "clients":  # 客戶分頁平常在切換客戶或離開時才存；關閉程式時也要存
            self.clients_page.save_current(quiet=True, prompt=False)
        self.update_settings(**{spec["setting"]: self.float_visible(key) for key, spec in self.FLOAT_SPECS.items()})
        self.data_manager.save_window_geometry("main_window", self)
        self.data_manager.flush()

    def quit_app(self):
        """真的結束程式（系統匣、把手選單使用）。停靠模式下按關閉只會收回側欄。"""
        self._quitting = True
        self.close()

    def closeEvent(self, e):
        if self.dock.active and not self._quitting:
            e.ignore()
            self.dock.slide_out()
            return
        if self._current_page == "clients" and not self.clients_page.save_current(quiet=True):
            # 客戶資料有問題（例如範本沒填名稱）時先不要關，讓使用者補好，免得編輯不見
            e.ignore()
            self._quitting = False
            self.restore_from_tray()
            return
        self.hotkey.unregister()
        self.dock.poll.stop()
        if self.dock.handle is not None:
            self.dock.handle.close()
        self.save_session_state()
        for window in self.floats.values():
            if window:
                window.close()
        if self.stats_window is not None:
            self.stats_window.close()
        self.topmost.stop()
        QApplication.instance().quit()
        e.accept()

    # --- 每秒／定期更新 ---

    def _tick(self):
        if self._current_page == "today" and self.isVisible():
            self.today_page.tick()
        self.update_work_status_label()
        self._update_pomodoro_float_display()
        self.dock.update_status(self.pomodoro_state)

    def _check_for_date_change(self):
        today = QDate.currentDate()
        if today != self.last_known_date:
            self.last_known_date = today
            self.refresh_overview_events()
            self.work_page._refresh_ui_states()
        if self._current_page == "today":
            self.today_page.refresh_tasks()
            self.today_page.refresh_income()

    def refresh_overview_events(self):
        self.events = self.data_manager.load_events()
        self.today_page.refresh_events()
        self.today_page.refresh_tasks()
        self.refresh_calendars()

    def refresh_tasks(self):
        self.today_page.refresh_tasks()
        self.today_page.refresh_income()
        self.refresh_calendars()

    def refresh_calendars(self):
        """行程或任務變動後，更新行事曆頁、懸浮日曆與週曆橫條。"""
        if self._current_page == "events":  # 不在這一頁時，切換過去才會重新整理
            self.calendar_page.refresh()
        self.refresh_stats()
        for key in ("calendar", "week"):
            window = self.floats.get(key)
            if window is not None:
                window.refresh_events()

    def show_statistics_window(self):  # 舊名稱
        self.navigate("stats")

    def refresh_stats(self):
        """資料變動後更新統計頁（目前看得到的才更新）和獨立的統計視窗。"""
        if self._current_page == "stats":
            self.stats_page.refresh()
        if self.stats_window is not None and self.stats_window.isVisible():
            self.stats_window.refresh()

    def open_stats_window(self):
        """在獨立視窗開啟統計；已經開著就叫到前面。"""
        if self.stats_window is None:
            self.stats_window = StatsWindow(self)
        page = self.stats_window.page
        if self._built("stats"):  # 沿用主視窗目前看的期間
            src = self.stats_page
            page.kind, page.year, page.month, page.currency = src.kind, src.year, src.month, src.currency
            page.kind_bar.set_current(src.kind)
            page.now_btn.setText(src.now_btn.text())
        if self.stats_window.isMinimized():
            self.stats_window.showNormal()
        self.stats_window.show()
        self.stats_window.raise_()
        self.stats_window.activateWindow()

    def edit_work_day(self, day):
        """修改某一天的打卡時間（統計頁、打卡紀錄頁使用）。"""
        from cocotimer.ui.dialogs import WorkSessionEditDialog
        from cocotimer.models import WorkRecord
        records = self.data_manager.load_work_records()
        record = records.get(day) or WorkRecord(date=day)  # 忘了打卡的日子也可以補登
        dialog = WorkSessionEditDialog(self.data_manager, day, [dict(s) for s in record.sessions], self)
        if dialog.exec():
            record.sessions = dialog.get_sessions()
            if record.sessions or day in records:
                records[day] = record
                self.data_manager.save_work_records(records)
                self._work_records_changed()

    def delete_work_day(self, day):
        if QMessageBox.question(self, "刪除打卡紀錄", f"確定要刪除 {day} 的所有打卡紀錄嗎？",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        records = self.data_manager.load_work_records()
        if records.pop(day, None) is not None:
            self.data_manager.save_work_records(records)
            self._work_records_changed()

    def _work_records_changed(self):
        self.work_page._refresh_ui_states()
        self.today_page.refresh_work()
        self.refresh_stats()

    # --- 番茄鐘 ---

    def pomodoro_status(self) -> dict:
        work_total = self.settings.pomodoro_work_minutes * 60
        if self.pomodoro_state == "idle":
            return {"state": "idle", "remaining": work_total, "total": work_total, "task": self._pomodoro_task_title()}
        if self.pomodoro_state == "paused":
            return {"state": "paused", "remaining": self._paused_remaining, "total": self._pomodoro_total,
                    "task": self._pomodoro_task_title()}
        remaining = max(0.0, (self.pomodoro_end_time - datetime.now()).total_seconds()) if self.pomodoro_end_time else 0
        return {"state": self.pomodoro_state, "remaining": remaining, "total": self._pomodoro_total,
                "task": self._pomodoro_task_title()}

    def _pomodoro_task_title(self):
        task = self.pomodoro_task()
        return task.title if task else ""

    # --- 番茄鐘與任務 ---

    def pomodoro_task(self):
        if not self.pomodoro_task_id:
            return None
        return next((t for t in self.task_page.tasks if t.id == self.pomodoro_task_id), None)

    def set_pomodoro_task(self, task_id):
        """切換專注的任務：先把目前這段專注時間記給原本的任務。"""
        task_id = task_id or ""
        if task_id == self.pomodoro_task_id:
            return
        self._credit_focus(restart=True)
        self.pomodoro_task_id = task_id
        self.update_settings(pomodoro_task_id=task_id)
        self.today_page.refresh_pomodoro()
        self._update_pomodoro_float_display()

    def _credit_focus(self, restart=False):
        """把還沒記錄的專注時間加到目前的任務。restart=True 時從現在重新起算（專注還在繼續）。"""
        if self._focus_started is None:
            return
        now = datetime.now()
        seconds = (now - self._focus_started).total_seconds()
        self._focus_started = now if restart else None
        if seconds < 1 or not self.pomodoro_task_id:
            return
        day = now.date().isoformat()
        stored = self.data_manager.load_tasks()
        task = next((t for t in stored if t.id == self.pomodoro_task_id), None)
        if task is None:
            return
        tasks_service.add_focus(task, seconds, day)
        self.data_manager.save_tasks(stored)
        # 任務頁手上的清單也要一起更新，否則之後在任務頁存檔會蓋掉這段時間
        mine = next((t for t in self.task_page.tasks if t.id == task.id), None)
        if mine is not None and mine is not task:
            mine.focus_log = dict(task.focus_log)

    def _start_phase(self, state, seconds):
        self._credit_focus()
        self._focus_started = datetime.now() if state == "working" else None
        self.pomodoro_state = state
        self._pomodoro_total = seconds
        self.pomodoro_end_time = datetime.now() + timedelta(seconds=seconds)
        self.pomodoro_timer.start(int(seconds * 1000))
        self.work_page.btn_pomodoro.setText("停止番茄鐘")
        self.work_page.start_pomodoro_timer()
        self._update_pomodoro_float_display()

    def _start_pomodoro_work(self):
        self._start_phase("working", self.settings.pomodoro_work_minutes * 60)

    def _start_pomodoro_break(self):
        self._start_phase("breaking", self.settings.pomodoro_break_minutes * 60)

    def _stop_pomodoro(self):
        self._credit_focus()
        self.pomodoro_state = "idle"
        self.pomodoro_end_time = None
        self.pomodoro_timer.stop()
        self.work_page.btn_pomodoro.setText("開始番茄鐘")
        self.work_page.stop_pomodoro_timer()
        self._update_pomodoro_float_display()

    def toggle_pomodoro(self):
        if self.pomodoro_state == "idle":
            self._start_pomodoro_work()
        else:
            self._stop_pomodoro()

    def pomodoro_primary_action(self):
        """開始／暫停／繼續。"""
        if self.pomodoro_state == "idle":
            self._start_pomodoro_work()
        elif self.pomodoro_state == "paused":
            self._start_phase(self._paused_phase, self._paused_remaining)
            self._pomodoro_total = self._paused_total
        else:
            self._paused_phase = self.pomodoro_state
            self._paused_total = self._pomodoro_total
            self._paused_remaining = self.pomodoro_status()["remaining"]
            self._credit_focus()
            self.pomodoro_timer.stop()
            self.pomodoro_state = "paused"
            self.pomodoro_end_time = None
            self._update_pomodoro_float_display()
        self.today_page.refresh_pomodoro()

    def pomodoro_skip(self):
        phase = self._paused_phase if self.pomodoro_state == "paused" else self.pomodoro_state
        if phase == "working":
            self._start_pomodoro_break()
        elif phase == "breaking":
            self._start_pomodoro_work()
        self.today_page.refresh_pomodoro()

    def pomodoro_reset(self):
        self._stop_pomodoro()
        self.today_page.refresh_pomodoro()

    def _update_pomodoro_timer(self):
        if self.settings.sound_enabled:
            self.sounds.play("pomodoro")
        if self.pomodoro_state == "working":
            self._start_pomodoro_break()
            self.show_toast("番茄鐘 🍅", f"工作結束！現在開始休息 {self.settings.pomodoro_break_minutes} 分鐘。")
        elif self.pomodoro_state == "breaking":
            self._start_pomodoro_work()
            self.show_toast("番茄鐘 🍅", "開始工作！")

    def _update_pomodoro_float_display(self):
        pomodoro, bar = self.floats.get("pomodoro"), self.floats.get("bar")
        if not (pomodoro and pomodoro.isVisible()) and not (bar and bar.isVisible()):
            return
        status = self.pomodoro_status()
        if pomodoro and pomodoro.isVisible():
            pomodoro.update_status(status)
        if bar and bar.isVisible():
            bar.update_pomodoro(status)

    # --- 打卡 ---

    def work_status(self) -> dict:
        """今天的打卡狀態：working、current（這一段的秒數）、total（今日累計秒數，含進行中這段）、sessions。"""
        today = datetime.now().strftime("%Y-%m-%d")
        key = (today, self.data_manager.version("work_records.json"))
        if getattr(self, "_work_cache_key", None) != key:  # 打卡紀錄沒變就不用每秒重新讀取
            self._work_cache_key = key
            self._work_cache = self.data_manager.load_work_records().get(today)
        rec = self._work_cache
        sessions = rec.sessions if rec else []
        total = rec.calculate_total_hours() * 3600 if rec else 0
        working = bool(sessions) and sessions[-1].get("end") is None
        current = 0
        if working:
            try:
                current = max(0.0, (datetime.now() - datetime.fromisoformat(sessions[-1]["start"])).total_seconds())
            except (KeyError, TypeError, ValueError):
                working = False
        return {"working": working, "current": current, "total": total + current, "sessions": len(sessions)}

    def update_work_status_label(self):
        work, bar = self.floats.get("work"), self.floats.get("bar")
        if not (work and work.isVisible()) and not (bar and bar.isVisible()):
            return
        status = self.work_status()
        if work and work.isVisible():
            work.update_status(status)
        if bar and bar.isVisible():
            bar.update_work(status)

    # --- 提醒 ---

    def check_notifications(self, force=False):
        """每秒呼叫一次，但只有「行程或任務有變動」或「到了下一個提醒時間」才真的重新檢查，平常幾乎不花 CPU。"""
        now = datetime.now()
        key = self.data_manager.version("events.json", "tasks.json")
        if not force and key == self._notify_key and (self._next_notify is None or now < self._next_notify):
            return
        upcoming = []  # 還沒到的提醒時間，用來決定下一次要檢查的時間

        current_events = self.data_manager.load_events()
        events_changed = False
        for e in current_events:
            if not e.notified and not e.completed:
                try:
                    t = datetime.strptime(f"{e.date} {e.time}", "%Y-%m-%d %H:%M")
                except ValueError:
                    continue
                if now < t:
                    upcoming.append(t)
                    continue
                if now >= t:
                    reminder_window = EventReminderWindow(e, self)
                    self.reminder_windows.append(reminder_window)
                    reminder_window.completed_signal.connect(self.mark_event_completed)
                    reminder_window.show()
                    if self.settings.sound_enabled:
                        self.sounds.play("reminder")
                    e.notified = True
                    events_changed = True
        if events_changed:
            self.data_manager.save_events(current_events)
            self.events = current_events
            self.refresh_overview_events()

        current_tasks = self.data_manager.load_tasks()
        tasks_changed = False
        for task in current_tasks:
            if task.completion >= 100:
                continue
            try:
                due_datetime = datetime.strptime(f"{task.due_date} {task.due_time}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            reminders = []
            before_time = due_datetime - timedelta(minutes=task.remind_before)
            if task.remind_before > 0 and not task.notified_before:
                if now >= before_time:
                    reminders.append(False)
                    task.notified_before = True
                else:
                    upcoming.append(before_time)
            if not task.notified_due:
                if now >= due_datetime:
                    reminders.append(True)
                    task.notified_due = True
                else:
                    upcoming.append(due_datetime)
            for is_due in reminders:
                reminder_window = TaskReminderWindow(task, is_due=is_due, parent=self)
                self.reminder_windows.append(reminder_window)
                reminder_window.completion_changed.connect(self.update_task_completion)
                reminder_window.show()
                if self.settings.sound_enabled:
                    self.sounds.play("reminder")
                tasks_changed = True

        if tasks_changed:
            self.data_manager.save_tasks(current_tasks)
            self.task_page.tasks = current_tasks
            self.task_page.update_task_list()
            self.refresh_tasks()
        self._notify_key = self.data_manager.version("events.json", "tasks.json")
        self._next_notify = min(upcoming) if upcoming else None

    def update_task_completion(self, task_id, new_completion):
        """更新任務完成度（從提醒視窗調用）"""
        current_tasks = self.data_manager.load_tasks()
        for task in current_tasks:
            if task.id == task_id:
                tasks_service.update_completion(task, new_completion)
                break
        self.data_manager.save_tasks(current_tasks)
        self.task_page.tasks = current_tasks
        self.task_page.update_task_list()
        self.refresh_tasks()

    def mark_event_completed(self, event_id):
        current_events = self.data_manager.load_events()
        for e in current_events:
            if e.id == event_id:
                e.completed = True
                break
        self.data_manager.save_events(current_events)
        self.events = current_events
        self.refresh_overview_events()

    def water_reminder(self):
        if self.settings.water_reminder_enabled:
            if self.settings.sound_enabled:
                self.sounds.play("water")
            self.show_toast("喝水提醒 💧", "該喝水囉！休息一下，保持身體水分～")


# 舊名稱（app.py 等仍使用）
TabbedMainWindow = MainWindow
