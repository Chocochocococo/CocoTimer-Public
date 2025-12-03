import sys
import json
import os
import re
import csv
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, TypedDict
from dataclasses import dataclass, asdict, field
from dateutil import tz
import calendar

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtMultimedia import QSoundEffect

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

APP_NAME = "CocoTimeManager_New"

def get_startup_command():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    else:
        python_exe = sys.executable.replace("python.exe", "pythonw.exe")
        script_path = os.path.abspath(__file__)
        return f'"{python_exe}" "{script_path}"'

def set_startup(enabled: bool):
    if sys.platform != 'win32':
        return
    try:
        import winreg
        key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
            if enabled:
                command = get_startup_command()
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            else:
                winreg.DeleteValue(key, APP_NAME)
        return True
    except (ImportError, FileNotFoundError, OSError):
        return False

def is_startup_enabled() -> bool:
    if sys.platform != 'win32': return False
    try:
        import winreg
        key_path = r'Software\Microsoft\Windows\CurrentVersion\Run'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except:
        return False

# --- 資料結構 ---

class WorkSession(TypedDict):
    start: str
    end: Optional[str]

@dataclass
class Event:
    id: str
    title: str
    date: str
    time: str
    description: str = ""
    notified: bool = False
    completed: bool = False

@dataclass
class TaskPriceItem:
    """任務價格項目"""
    name: str  # 項目名稱
    unit_price: float  # 單價
    quantity: float  # 數量

    def get_subtotal(self) -> float:
        """計算小計"""
        return self.unit_price * self.quantity

@dataclass
class TaskItem:
    """工作任務"""
    id: str
    project_name: str  # 專案名稱
    title: str  # 任務標題
    due_date: str  # 交件日期（YYYY-MM-DD）
    due_time: str  # 交件時間（HH:MM）
    client: str  # 客戶
    description: str  # 描述
    completion: int  # 完成度百分比（0-100）
    price_items: List[Dict] = field(default_factory=list)  # 價格項目列表
    currency: str = "NTD"  # 幣別（預設台幣）
    remind_before: int = 0  # 提前提醒分鐘數（0表示不提醒）
    created_date: str = ""  # 建立日期
    created_time: str = ""  # 建立時間
    notified_before: bool = False  # 是否已提前提醒
    notified_due: bool = False  # 是否已到期提醒

    def get_total_price(self) -> float:
        """計算總價"""
        total = 0.0
        for item in self.price_items:
            total += item.get('unit_price', 0) * item.get('quantity', 0)
        return total

    def is_overdue(self) -> bool:
        """是否已逾期"""
        if self.completion >= 100:
            return False
        now = datetime.now()
        due_datetime_str = f"{self.due_date} {self.due_time}"
        try:
            due_datetime = datetime.strptime(due_datetime_str, "%Y-%m-%d %H:%M")
            return now > due_datetime
        except:
            return False

@dataclass
class WorkRecord:
    date: str
    sessions: List[WorkSession] = field(default_factory=list)
    
    def calculate_total_hours(self) -> float:
        total_seconds = 0
        for session in self.sessions:
            if session.get('start') and session.get('end'):
                start_dt = datetime.fromisoformat(session['start'])
                end_dt = datetime.fromisoformat(session['end'])
                total_seconds += (end_dt - start_dt).total_seconds()
        return total_seconds / 3600.0

@dataclass
class ThemeConfig:
    bg_color: str = "#FFF7ED"          # 背景色
    text_color: str = "#5B3A29"        # 主要文字色 (平日日期)
    btn_color: str = "#F9EEE4"         # 按鈕背景
    btn_hover: str = "#F2D7C3"         # 按鈕懸停
    border_color: str = "#EEDAC8"      # 邊框顏色
    accent_color: str = "#D4A373"      # 強調色 (今天)
    weekend_color: str = "#C83B3B"     # 週末文字顏色
    other_month_color: str = "#B89A8C" # <<< NEW: 非本月日期顏色 (灰) >>>
    event_highlight_color: str = "#F2D7C3" # 行程日期高亮色
    font_family: str = "Noto Sans TC"
    base_font_size: int = 10
    font_bold: bool = False            # 字體是否粗體
    font_italic: bool = False          # 字體是否斜體
    font_underline: bool = False       # 字體是否底線
    font_strikeout: bool = False       # 字體是否刪除線
    font_weight: int = 400             # 字體粗細 (100-900, 400=normal, 700=bold)

@dataclass
class Settings:
    water_reminder_interval: int = 15
    water_reminder_enabled: bool = True
    pomodoro_work_minutes: int = 25
    pomodoro_break_minutes: int = 5
    sound_enabled: bool = True
    clock_visible: bool = False
    calendar_visible: bool = False
    volume: float = 0.8
    pomodoro_float_visible: bool = False
    work_time_float_visible: bool = False
    max_completed_tasks: int = 10  # 過去任務顯示筆數
    theme: ThemeConfig = field(default_factory=ThemeConfig)

# --- 資料管理器 ---
class DataManager:
    def __init__(self):
        self.data_dir = os.path.join(BASE_DIR, "timemanager_data")
        self.ensure_data_dir()

    def _ws_path(self):
        return f"{self.data_dir}/window_state.json"
    
    def ensure_data_dir(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
    def save_events(self, events: List[Event]):
        with open(f"{self.data_dir}/events.json", "w", encoding="utf-8") as f:
            json.dump([asdict(event) for event in events], f, ensure_ascii=False, indent=2)
            
    def load_events(self) -> List[Event]:
        try:
            with open(f"{self.data_dir}/events.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return [Event(**item) for item in data]
        except (FileNotFoundError, json.JSONDecodeError):
            return []
            
    def save_work_records(self, records: Dict[str, WorkRecord]):
        with open(f"{self.data_dir}/work_records.json", "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in records.items()}, f, ensure_ascii=False, indent=2)
            
    def load_work_records(self) -> Dict[str, WorkRecord]:
        try:
            with open(f"{self.data_dir}/work_records.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return {k: WorkRecord(**v) for k, v in data.items()}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_tasks(self, tasks: List[TaskItem]):
        with open(f"{self.data_dir}/tasks.json", "w", encoding="utf-8") as f:
            json.dump([asdict(task) for task in tasks], f, ensure_ascii=False, indent=2)

    def load_tasks(self) -> List[TaskItem]:
        try:
            with open(f"{self.data_dir}/tasks.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return [TaskItem(**item) for item in data]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_settings(self, settings: Settings):
        with open(f"{self.data_dir}/settings.json", "w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, ensure_ascii=False, indent=2)
            
    def load_settings(self) -> Settings:
        try:
            with open(f"{self.data_dir}/settings.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                if "theme" in data:
                    data["theme"] = ThemeConfig(**data["theme"])
                return Settings(**data)
        except (FileNotFoundError, json.JSONDecodeError):
            return Settings()
        
    def save_window_geometry(self, name: str, widget: QWidget):
        try:
            from PySide6.QtCore import QByteArray
            geo_hex = bytes(widget.saveGeometry().toHex()).decode()
            data = {}
            if os.path.exists(self._ws_path()):
                with open(self._ws_path(), "r", encoding="utf-8") as f:
                    data = json.load(f)
            data[name] = {"geometry": geo_hex}
            with open(self._ws_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def restore_window_geometry(self, name: str, widget: QWidget):
        try:
            from PySide6.QtCore import QByteArray
            if not os.path.exists(self._ws_path()): return False
            with open(self._ws_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if name in data and "geometry" in data[name]:
                geo = QByteArray.fromHex(data[name]["geometry"].encode())
                widget.restoreGeometry(geo)
                return True
        except Exception:
            pass
        return False

# --- 輔助工具：顏色轉換 ---
def hex_to_rgba(hex_color, alpha=255):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        return QColor(r, g, b, alpha)
    return QColor(hex_color)

# --- UI 元件 ---

class ToastNotification(QWidget):
    def __init__(self, title, message, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.title_label = QLabel(title)
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)

        self.title_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold; background: transparent;")
        self.message_label.setStyleSheet("color: #E0E0E0; font-size: 14px; background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)

        self.setFixedWidth(550)
        self.adjustSize()

        if parent:
            parent_rect = parent.geometry()
            self.move(parent_rect.center() - self.rect().center())

        # 初始化動畫物件
        self.animation = QPropertyAnimation(self, b"windowOpacity", self)
        
        # 修改 2: 設定為 5000 毫秒 (5秒) 後開始淡出，比原本的 3 秒更久且有緩衝
        QTimer.singleShot(5000, self.fade_out)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 15, 15)
        
        # 修改 1: 改回舊版的深灰色 (40, 40, 40) 與透明度 230
        # 原本是純黑 (0, 0, 0, 200)
        painter.fillPath(path, QColor(40, 40, 40, 230))

    def showEvent(self, event):
        # 加入淡入動畫
        self.animation.setDuration(300)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
        super().showEvent(event)

    def fade_out(self):
        # 執行淡出動畫，結束後才關閉視窗
        self.animation.setDuration(500)
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.close)
        self.animation.start()

class CalendarTooltip(QFrame):
    """Popup tooltip for calendar that stays visible until clicking elsewhere."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("background: transparent;")
        layout.addWidget(self.label)

    def set_content(self, theme, html):
        self.label.setText(html)
        self.setStyleSheet(
            f"QFrame {{ background: {theme.bg_color}; color: {theme.text_color}; "
            f"border: 2px solid {theme.border_color}; border-radius: 10px; padding: 8px; }}"
            f"QLabel {{ color: {theme.text_color}; background: transparent; }}"
        )

    def show_at(self, global_pos):
        self.adjustSize()
        self.move(global_pos)
        self.show()

class EventReminderWindow(QWidget):
    completed_signal = Signal(str)
    
    def __init__(self, event: Event, parent=None):
        super().__init__(parent)
        self.event_data = event 
        self.drag_position = QPoint()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.init_ui()
        self.center_on_screen()
        
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        container = QWidget()
        container.setStyleSheet("QWidget { background-color: #2C3E50; border-radius: 15px; }")
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(15)
        
        title = QLabel("⏰ 行程提醒")
        title.setStyleSheet("color: #ECF0F1; font-size: 18px; font-weight: bold; background: transparent;")
        layout.addWidget(title)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #34495E;")
        layout.addWidget(line)
        
        event_title = QLabel(f"📌 {self.event_data.title}") 
        event_title.setStyleSheet("color: #3498DB; font-size: 16px; font-weight: bold; background: transparent;")
        event_title.setWordWrap(True)
        layout.addWidget(event_title)
        
        event_time = QLabel(f"🕐 {self.event_data.date} {self.event_data.time}")
        event_time.setStyleSheet("color: #95A5A6; font-size: 14px; background: transparent;")
        layout.addWidget(event_time)
        
        if self.event_data.description:
            desc_label = QLabel(f"📝 {self.event_data.description}")
            desc_label.setStyleSheet("color: #BDC3C7; font-size: 13px; background: transparent;")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)
        
        self.completed_checkbox = QCheckBox("標記為已完成")
        self.completed_checkbox.setStyleSheet("""
            QCheckBox { color: #ECF0F1; font-size: 14px; background: transparent; spacing: 8px; }
            QCheckBox::indicator { width: 20px; height: 20px; border-radius: 4px; border: 2px solid #7F8C8D; background-color: #34495E; }
            QCheckBox::indicator:checked { background-color: #27AE60; border-color: #27AE60; }
        """)
        layout.addWidget(self.completed_checkbox)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.ok_btn = QPushButton("確定")
        self.ok_btn.setStyleSheet("""
            QPushButton { background-color: #3498DB; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background-color: #2980B9; }
        """)
        self.ok_btn.clicked.connect(self.on_ok_clicked)
        btn_layout.addStretch()
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        main_layout.addWidget(container)
        self.setFixedWidth(400)
        self.adjustSize()
    
    def center_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.center() - self.rect().center())
    
    def on_ok_clicked(self):
        if self.completed_checkbox.isChecked():
            self.completed_signal.emit(self.event_data.id)
        self.close()
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

class TaskReminderWindow(QWidget):
    """任務提醒視窗"""
    completion_changed = Signal(str, int)  # 發送任務ID和新的完成度

    def __init__(self, task: 'TaskItem', is_due=False, parent=None):
        super().__init__(parent)
        self.task_data = task
        self.is_due = is_due  # True表示到期提醒，False表示提前提醒
        self.drag_position = QPoint()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.init_ui()
        self.center_on_screen()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        container.setStyleSheet("QWidget { background-color: #2C3E50; border-radius: 15px; }")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(15)

        title_text = "⏰ 任務到期提醒" if self.is_due else "⏰ 任務提前提醒"
        title = QLabel(title_text)
        title.setStyleSheet("color: #ECF0F1; font-size: 18px; font-weight: bold; background: transparent;")
        layout.addWidget(title)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #34495E;")
        layout.addWidget(line)

        task_title = QLabel(f"📋 {self.task_data.title}")
        task_title.setStyleSheet("color: #3498DB; font-size: 16px; font-weight: bold; background: transparent;")
        task_title.setWordWrap(True)
        layout.addWidget(task_title)

        project_label = QLabel(f"📁 專案: {self.task_data.project_name}")
        project_label.setStyleSheet("color: #95A5A6; font-size: 14px; background: transparent;")
        layout.addWidget(project_label)

        due_time = QLabel(f"🕐 交件時間: {self.task_data.due_date} {self.task_data.due_time}")
        due_time.setStyleSheet("color: #95A5A6; font-size: 14px; background: transparent;")
        layout.addWidget(due_time)

        # 完成度調整區域
        completion_container = QWidget()
        completion_container.setStyleSheet("background: transparent;")
        completion_layout = QVBoxLayout(completion_container)
        completion_layout.setContentsMargins(0, 0, 0, 0)
        completion_layout.setSpacing(8)

        completion_title = QLabel("📊 調整完成度:")
        completion_title.setStyleSheet("color: #95A5A6; font-size: 14px; background: transparent;")
        completion_layout.addWidget(completion_title)

        slider_row = QWidget()
        slider_row.setStyleSheet("background: transparent;")
        slider_layout = QHBoxLayout(slider_row)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(10)

        self.completion_slider = QSlider(Qt.Horizontal)
        self.completion_slider.setMinimum(0)
        self.completion_slider.setMaximum(100)
        self.completion_slider.setValue(self.task_data.completion)
        self.completion_slider.setStyleSheet("""
            QSlider::groove:horizontal { background: #34495E; height: 8px; border-radius: 4px; }
            QSlider::handle:horizontal { background: #3498DB; width: 18px; height: 18px; margin: -5px 0; border-radius: 9px; }
            QSlider::handle:horizontal:hover { background: #2980B9; }
        """)
        self.completion_slider.valueChanged.connect(self._update_completion_label)
        slider_layout.addWidget(self.completion_slider)

        self.completion_value_label = QLabel(f"{self.task_data.completion}%")
        self.completion_value_label.setStyleSheet("color: #ECF0F1; font-size: 14px; font-weight: bold; background: transparent; min-width: 50px;")
        slider_layout.addWidget(self.completion_value_label)

        completion_layout.addWidget(slider_row)
        layout.addWidget(completion_container)

        if self.task_data.description:
            desc_label = QLabel(f"📝 {self.task_data.description}")
            desc_label.setStyleSheet("color: #BDC3C7; font-size: 13px; background: transparent;")
            desc_label.setWordWrap(True)
            layout.addWidget(desc_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.ok_btn = QPushButton("確定")
        self.ok_btn.setStyleSheet("""
            QPushButton { background-color: #3498DB; color: white; border: none; border-radius: 6px; padding: 10px 20px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background-color: #2980B9; }
        """)
        self.ok_btn.clicked.connect(self._on_ok_clicked)
        btn_layout.addStretch()
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        main_layout.addWidget(container)
        self.setFixedWidth(400)
        self.adjustSize()

    def _update_completion_label(self, value):
        """更新完成度標籤"""
        self.completion_value_label.setText(f"{value}%")

    def _on_ok_clicked(self):
        """確定按鈕點擊時儲存完成度"""
        new_completion = self.completion_slider.value()
        if new_completion != self.task_data.completion:
            self.completion_changed.emit(self.task_data.id, new_completion)
        self.close()

    def center_on_screen(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.center() - self.rect().center())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

class DraggableResizableWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.dragging = False
        self.resizing = False
        self.drag_position = QPoint()
        self.resize_grip_size = 20
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.is_in_resize_area(event.position().toPoint()):
                self.resizing = True
                self.resize_start_pos = event.position().toPoint()
                self.resize_start_size = self.size()
            else:
                self.dragging = True
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        
    def mouseMoveEvent(self, event):
        if self.dragging and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
        elif self.resizing and event.buttons() == Qt.LeftButton:
            delta = event.position().toPoint() - self.resize_start_pos
            new_size = QSize(
                max(200, self.resize_start_size.width() + delta.x()),
                max(120, self.resize_start_size.height() + delta.y())
            )
            self.resize(new_size)
            
    def mouseReleaseEvent(self, event):
        self.dragging = False
        self.resizing = False
        
    def is_in_resize_area(self, pos):
        rect = self.rect()
        return (pos.x() > rect.width() - self.resize_grip_size and 
                pos.y() > rect.height() - self.resize_grip_size)

class PomodoroFloatWindow(DraggableResizableWindow):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.setWindowTitle("番茄鐘")
        self.resize(280, 120)
        self.setup_ui()
        self.data_manager.restore_window_geometry("pomodoro_float", self)
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(8)
        self.title_label = QLabel("🍅 番茄鐘")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.status_label = QLabel("未啟動")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        self.update_style() 
        self._update_font_sizes()
    
    def update_style(self):
        theme = self.data_manager.load_settings().theme
        self.title_label.setStyleSheet(f"color: {theme.text_color}; font-weight: bold; background: transparent; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif;")
        self.status_label.setStyleSheet(f"color: {theme.text_color}; font-weight: bold; background: transparent; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif;")
        self.update()

    def _update_font_sizes(self):
        theme = self.data_manager.load_settings().theme
        h = max(1, self.height())
        title_px = max(12, int(h * 0.12))
        title_font = self.title_label.font()
        title_font.setFamily(theme.font_family)
        title_font.setPixelSize(title_px)
        title_font.setBold(theme.font_bold)
        title_font.setItalic(theme.font_italic)
        title_font.setUnderline(theme.font_underline)
        title_font.setStrikeOut(theme.font_strikeout)
        title_font.setWeight(QFont.Weight(theme.font_weight))
        self.title_label.setFont(title_font)
        status_px = max(16, int(h * 0.16))
        status_font = self.status_label.font()
        status_font.setFamily(theme.font_family)
        status_font.setPixelSize(status_px)
        status_font.setBold(theme.font_bold)
        status_font.setItalic(theme.font_italic)
        status_font.setUnderline(theme.font_underline)
        status_font.setStrikeOut(theme.font_strikeout)
        status_font.setWeight(QFont.Weight(theme.font_weight))
        self.status_label.setFont(status_font)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_font_sizes()
        self.data_manager.save_window_geometry("pomodoro_float", self)
    
    def update_display(self, text):
        self.status_label.setText(text)
    
    def closeEvent(self, event):
        self.data_manager.save_window_geometry("pomodoro_float", self)
        super().closeEvent(event)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        theme = self.data_manager.load_settings().theme
        bg_color = hex_to_rgba(theme.bg_color, 220) 
        border_color = hex_to_rgba(theme.border_color, 180)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 15, 15)
        painter.fillPath(path, bg_color)
        pen = QPen(border_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPath(path)

class WorkTimeFloatWindow(DraggableResizableWindow):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.setWindowTitle("工時計時")
        self.resize(280, 120)
        self.setup_ui()
        self.data_manager.restore_window_geometry("work_time_float", self)
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(8)
        self.title_label = QLabel("⏰ 工時計時")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.status_label = QLabel("未打卡")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status_label)
        self.update_style()
        self._update_font_sizes()
    
    def update_style(self):
        theme = self.data_manager.load_settings().theme
        self.title_label.setStyleSheet(f"color: {theme.text_color}; font-weight: bold; background: transparent; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif;")
        self.status_label.setStyleSheet(f"color: {theme.text_color}; font-weight: bold; background: transparent; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif;")
        self.update()

    def _update_font_sizes(self):
        theme = self.data_manager.load_settings().theme
        h = max(1, self.height())
        title_px = max(12, int(h * 0.12))
        title_font = self.title_label.font()
        title_font.setFamily(theme.font_family)
        title_font.setPixelSize(title_px)
        title_font.setBold(theme.font_bold)
        title_font.setItalic(theme.font_italic)
        title_font.setUnderline(theme.font_underline)
        title_font.setStrikeOut(theme.font_strikeout)
        title_font.setWeight(QFont.Weight(theme.font_weight))
        self.title_label.setFont(title_font)
        status_px = max(16, int(h * 0.16))
        status_font = self.status_label.font()
        status_font.setFamily(theme.font_family)
        status_font.setPixelSize(status_px)
        status_font.setBold(theme.font_bold)
        status_font.setItalic(theme.font_italic)
        status_font.setUnderline(theme.font_underline)
        status_font.setStrikeOut(theme.font_strikeout)
        status_font.setWeight(QFont.Weight(theme.font_weight))
        self.status_label.setFont(status_font)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_font_sizes()
        self.data_manager.save_window_geometry("work_time_float", self)
    
    def update_display(self, text):
        self.status_label.setText(text)
    
    def closeEvent(self, event):
        self.data_manager.save_window_geometry("work_time_float", self)
        super().closeEvent(event)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        theme = self.data_manager.load_settings().theme
        bg_color = hex_to_rgba(theme.bg_color, 220)
        border_color = hex_to_rgba(theme.border_color, 180)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 15, 15)
        painter.fillPath(path, bg_color)
        pen = QPen(border_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPath(path)

class DigitalClock(DraggableResizableWindow):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.setWindowTitle("數字時鐘")
        self.resize(420, 160)
        self.weekdays_ch = ["（一）", "（二）", "（三）", "（四）", "（五）", "（六）", "（日）"]
        
        self.setup_ui() 
        
        self.data_manager.restore_window_geometry("digital_clock", self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)
        self.update_time()

    def setup_ui(self):
        layout = QVBoxLayout(self) 
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)
        
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignCenter)
        
        self.date_label = QLabel()
        self.date_label.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(self.time_label, 2)
        layout.addWidget(self.date_label, 1)
        self.update_style()
        self._apply_font_sizes()

    def update_style(self):
        theme = self.data_manager.load_settings().theme
        style = f"color: {theme.text_color}; background: transparent; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif; font-weight: 700;"
        self.time_label.setStyleSheet(style)
        self.date_label.setStyleSheet(style)
        self.update()

    def update_time(self):
        now = datetime.now()
        self.time_label.setText(now.strftime("%H:%M:%S"))
        weekday_str = self.weekdays_ch[now.weekday()]
        date_str = now.strftime(f"%Y年%m月%d日 {weekday_str}")
        self.date_label.setText(date_str)

    def _apply_font_sizes(self):
        theme = self.data_manager.load_settings().theme
        h = max(1, self.height())
        time_px = max(28, int(h * 0.38))
        date_px = max(16, int(h * 0.13))
        tf = self.time_label.font()
        tf.setFamily(theme.font_family)
        tf.setPixelSize(time_px)
        tf.setBold(theme.font_bold)
        tf.setItalic(theme.font_italic)
        tf.setUnderline(theme.font_underline)
        tf.setStrikeOut(theme.font_strikeout)
        tf.setWeight(QFont.Weight(theme.font_weight))
        self.time_label.setFont(tf)
        df = self.date_label.font()
        df.setFamily(theme.font_family)
        df.setPixelSize(date_px)
        df.setBold(theme.font_bold)
        df.setItalic(theme.font_italic)
        df.setUnderline(theme.font_underline)
        df.setStrikeOut(theme.font_strikeout)
        df.setWeight(QFont.Weight(theme.font_weight))
        self.date_label.setFont(df)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        theme = self.data_manager.load_settings().theme
        bg_color = hex_to_rgba(theme.bg_color, 150) # 較透明
        border_color = hex_to_rgba(theme.border_color, 150)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 20, 20)
        painter.fillPath(path, bg_color)
        pen = QPen(border_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPath(path)

    def moveEvent(self, e):
        super().moveEvent(e)
        self.data_manager.save_window_geometry("digital_clock", self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_font_sizes()
        self.data_manager.save_window_geometry("digital_clock", self)

_LUNAR_DAY_PATTERN = re.compile(
    r"月(初[一二三四五六七八九十]"
    r"|十[一二三四五六七八九]"
    r"|二十(?:[一二三四五六七八九])?"
    r"|廿[一二三四五六七八九]?"
    r"|三十)"
)

def _lunar_day_name(y, m, d) -> str:
    try:
        from zhdate import ZhDate
        from datetime import datetime as _dt
        z = ZhDate.from_datetime(_dt(y, m, d))
        s = z.chinese().replace(" ", "")
        mobj = _LUNAR_DAY_PATTERN.search(s)
        return mobj.group(1) if mobj else ""
    except Exception:
        return ""

class LunarCalendar(QCalendarWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._event_dates = set()
        self.text_color = QColor("#5B3A29")
        self.other_month_color = QColor("#B89A8C")
        self.weekend_color = QColor("#C83B3B")
        self.event_highlight_color = QColor("#F2D7C3")
        self.font_family = "Noto Sans TC"
        self.font_bold = False
        self.font_italic = False
        self.font_underline = False
        self.font_strikeout = False
        self.font_weight = 400

    def set_event_dates(self, dates):
        self._event_dates = set(dates)
        self.update()

    def set_theme_colors(self, text_col, other_col, weekend_col, highlight_col):
        self.text_color = QColor(text_col)
        self.other_month_color = QColor(other_col)
        self.weekend_color = QColor(weekend_col)
        self.event_highlight_color = QColor(highlight_col)
        self.update()

    def set_font_family(self, font_family):
        self.font_family = font_family
        self.update()

    def set_font_styles(self, bold, italic, underline, strikeout, weight):
        self.font_bold = bold
        self.font_italic = italic
        self.font_underline = underline
        self.font_strikeout = strikeout
        self.font_weight = weight
        self.update()

    def paintCell(self, painter: QPainter, rect: QRect, date: QDate):
        # 判斷是否為今天
        is_today = (date == QDate.currentDate())
        
        # <<< FIX: 如果是今天，先畫背景色 >>>
        if is_today:
            painter.save()
            rr = rect.adjusted(2, 2, -2, -2)
            path = QPainterPath()
            path.addRoundedRect(QRectF(rr), 6, 6)
            today_color = QColor(self.event_highlight_color)
            today_color.setAlpha(255)  # 今天的背景完全不透明
            painter.fillPath(path, QColor("#D4A373"))  # 使用主題的 accent_color
            painter.restore()
        
        # <<< FIX: 先畫高亮背景 (在文字下面) >>>
        elif date in self._event_dates:
            painter.save()
            rr = rect.adjusted(2, 2, -2, -2)
            path = QPainterPath()
            path.addRoundedRect(QRectF(rr), 6, 6)
            hl_color = QColor(self.event_highlight_color)
            hl_color.setAlpha(180) 
            painter.fillPath(path, hl_color) 
            painter.restore()

        # 判斷是否為本月日期
        in_month = (date.month() == self.monthShown() and date.year() == self.yearShown())
        
        # <<< FIX: 手動繪製國曆日期，以便控制顏色 >>>
        painter.save()
        
        # 設定國曆日期的顏色和字重
        if is_today:
            # 今天的日期用白色並加粗
            painter.setPen(QColor("white"))
            font_weight = QFont.Bold
        elif in_month:
            if date.dayOfWeek() >= 6:
                painter.setPen(self.weekend_color)
            else:
                painter.setPen(self.text_color)
            font_weight = QFont.DemiBold
        else:
            # 非本月日期使用 other_month_color
            painter.setPen(self.other_month_color)
            font_weight = QFont.DemiBold
        
        # 繪製國曆日期（日期數字）
        # 使用更大的字體，讓國曆日期清晰可見
        day_px = max(13, int(min(rect.width(), rect.height()) * 0.28))
        f = painter.font()
        f.setFamily(self.font_family)
        f.setPixelSize(day_px)
        f.setWeight(font_weight)
        f.setItalic(self.font_italic)
        f.setUnderline(self.font_underline)
        f.setStrikeOut(self.font_strikeout)
        painter.setFont(f)
        
        # 將日期數字繪製在格子的上半部
        day_rect = QRect(rect.left()+2, rect.top()+int(rect.height()*0.15),
                        rect.width()-4, int(rect.height()*0.45))
        painter.drawText(day_rect, Qt.AlignHCenter | Qt.AlignVCenter, str(date.day()))
        painter.restore()
        
        # 繪製農曆日期
        lunar_day = _lunar_day_name(date.year(), date.month(), date.day())
        if lunar_day:
            painter.save()
            
            # 農曆日期使用相同的顏色邏輯
            if is_today:
                painter.setPen(QColor("white"))
            elif in_month:
                if date.dayOfWeek() >= 6:
                    painter.setPen(self.weekend_color)
                else:
                    painter.setPen(self.text_color)
            else:
                painter.setPen(self.other_month_color)
            
            px = max(9, int(min(rect.width(), rect.height()) * 0.12))
            f = painter.font()
            f.setFamily(self.font_family)
            f.setPixelSize(px)
            f.setBold(self.font_bold)
            f.setItalic(self.font_italic)
            f.setUnderline(self.font_underline)
            f.setStrikeOut(self.font_strikeout)
            f.setWeight(QFont.Weight(self.font_weight))
            painter.setFont(f)
            r = QRect(rect.left()+2, rect.top()+int(rect.height()*0.62),
                    rect.width()-4, int(rect.height()*0.34))
            painter.drawText(r, Qt.AlignHCenter | Qt.AlignVCenter, lunar_day)
            painter.restore()

class CalendarWidget(DraggableResizableWindow):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.events = self.data_manager.load_events()
        self.tasks = self.data_manager.load_tasks()
        self.tooltip_popup = None
        self.setWindowTitle("日曆")
        self.resize(460, 420)
        self.setup_ui()
        self.data_manager.restore_window_geometry("calendar_window", self)

    def moveEvent(self, e):
        super().moveEvent(e)
        self.data_manager.save_window_geometry("calendar_window", self)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        self.title_label = QLabel("行事曆")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.calendar = LunarCalendar()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        today_btn = QPushButton("📅 今天")
        today_btn.setStyleSheet("""
            QPushButton { background-color: #D4A373; color: white; border: none; border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background-color: #C08F5D; }
        """)
        today_btn.clicked.connect(self.jump_to_today)
        
        self._apply_calendar_theme()
        self.calendar.currentPageChanged.connect(lambda *_: (self._apply_calendar_theme(), self.update_calendar_highlights()))
        self.calendar.clicked[QDate].connect(self.show_events_for_date)
        self.last_date = QDate.currentDate()
        self.day_check_timer = QTimer(self)
        self.day_check_timer.timeout.connect(self.check_day_change)
        self.day_check_timer.start(60000)
        self.update_calendar_highlights()
        
        layout.addWidget(self.title_label)
        layout.addWidget(today_btn)
        layout.addWidget(self.calendar)
    
    def jump_to_today(self):
        self.calendar.setSelectedDate(QDate.currentDate())
        self.calendar.showToday()
    
    def check_day_change(self):
        current_date = QDate.currentDate()
        if current_date != self.last_date:
            self.last_date = current_date
            self.calendar.updateCells()

    def show_events_for_date(self, date):
        date_str = date.toString("yyyy-MM-dd")
        events_on_date = [e for e in self.events if e.date == date_str]
        tasks_on_date = [t for t in self.tasks if t.due_date == date_str]
        if not events_on_date and not tasks_on_date:
            return
        events_on_date.sort(key=lambda x: x.time)
        tasks_on_date.sort(key=lambda x: x.due_time)
        theme = self.data_manager.load_settings().theme
        tooltip_parts = [f"<div style='color:{theme.text_color}; min-width:220px;'>"]
        tooltip_parts.append(f"<b style='color:{theme.text_color}; font-size:12pt;'>{date_str}</b>")
        tooltip_parts.append(f"<hr style='border:1px solid {theme.border_color}; margin:6px 0;'>")
        if events_on_date:
            tooltip_parts.append(f"<span style='color:{theme.accent_color}; font-weight:700;'>行程</span><br>")
            for event in events_on_date:
                tooltip_parts.append(f"{event.time} - {event.title}<br>")
                if event.description:
                    tooltip_parts.append(f"<span style='color:{theme.text_color}; font-size:9pt;'>※{event.description}</span><br>")
        if tasks_on_date:
            tooltip_parts.append(f"<span style='color:{theme.accent_color}; font-weight:700;'>任務</span><br>")
            for task in tasks_on_date:
                tooltip_parts.append(f"{task.due_time} - {task.title} ({task.project_name}) [{task.completion}%]<br>")
        tooltip_parts.append("</div>")
        html = "".join(tooltip_parts)
        if self.tooltip_popup:
            self.tooltip_popup.close()
        self.tooltip_popup = CalendarTooltip(self)
        self.tooltip_popup.set_content(theme, html)
        pos = QCursor.pos() + QPoint(12, 12)
        self.tooltip_popup.show_at(pos)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_font_sizes()
        self.data_manager.save_window_geometry("calendar_window", self)

    def _apply_font_sizes(self):
        theme = self.data_manager.load_settings().theme
        base = max(12, int(min(self.width(), self.height()) * 0.035))
        title_px = max(16, int(base * 1.3))
        grid_px = base
        tf = self.title_label.font()
        tf.setFamily(theme.font_family)
        tf.setPixelSize(title_px)
        tf.setWeight(QFont.DemiBold)
        tf.setItalic(theme.font_italic)
        tf.setUnderline(theme.font_underline)
        tf.setStrikeOut(theme.font_strikeout)
        self.title_label.setFont(tf)
        cal_font = self.calendar.font()
        cal_font.setFamily(theme.font_family)
        cal_font.setPixelSize(grid_px)
        cal_font.setBold(theme.font_bold)
        cal_font.setItalic(theme.font_italic)
        cal_font.setUnderline(theme.font_underline)
        cal_font.setStrikeOut(theme.font_strikeout)
        cal_font.setWeight(QFont.Weight(theme.font_weight))
        self.calendar.setFont(cal_font)
        self.calendar.set_font_family(theme.font_family)
        self.calendar.set_font_styles(theme.font_bold, theme.font_italic, theme.font_underline, theme.font_strikeout, theme.font_weight)
        nav_px = max(14, int(base * 1.1))
        self._apply_calendar_theme(nav_px)

    def _apply_calendar_theme(self, nav_px=None):
        if nav_px is None:
            nav_px = max(14, int(min(self.width(), self.height()) * 0.035 * 1.1))
            
        theme = self.data_manager.load_settings().theme
        
        self.calendar.set_theme_colors(
            theme.text_color, 
            theme.other_month_color, 
            theme.weekend_color, 
            theme.event_highlight_color
        )

        self.title_label.setStyleSheet(f"color: {theme.text_color}; background: transparent; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif;")
        
        # <<< FIX: 設定 disabled 顏色 >>>
        qss = f"""
        QCalendarWidget {{ background: transparent; border-radius: 12px; }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: rgba(255, 255, 255, 0.4); border-radius: 10px; padding: 4px; }}
        QCalendarWidget QToolButton {{ color: {theme.text_color}; border: 1px solid {theme.border_color}; border-radius: 8px; padding: 4px 10px; font-weight: 600; font-size: {nav_px}px; background: transparent; }}
        QCalendarWidget QToolButton:hover {{ background: {theme.btn_hover}; }}
        
        QCalendarWidget QAbstractItemView, QCalendarWidget QTableView {{ background-color: transparent; alternate-background-color: transparent; gridline-color: {theme.border_color}; outline: none; }}
        
        QCalendarWidget QAbstractItemView::item {{ background-color: {theme.bg_color}; font-weight: 600; border: none; padding: 4px; }}
        
        /* 非本月日期 (Disabled) */
        QCalendarWidget QAbstractItemView::item:disabled {{ background-color: transparent; color: {theme.other_month_color}; }}
        
        QCalendarWidget QAbstractItemView::item:selected {{ background-color: {theme.btn_hover}; color: {theme.text_color}; }}
        QCalendarWidget QAbstractItemView::item:hover {{ background-color: {theme.btn_color}; }}
        """
        self.calendar.setStyleSheet(qss)
        
        for btn in self.findChildren(QPushButton):
            if btn.text() == "📅 今天":
                btn.setStyleSheet(f"""
                    QPushButton {{ background-color: {theme.accent_color}; color: white; border: none; border-radius: 6px; padding: 8px 16px; font-size: 13px; font-weight: bold; }}
                    QPushButton:hover {{ background-color: {theme.btn_hover}; color: {theme.text_color}; }}
                """)

    def update_calendar_highlights(self):
        theme = self.data_manager.load_settings().theme
        
        default_fmt = QTextCharFormat()
        # <<< FIX: 不要設定預設前景色，讓 CSS 決定 >>>
        # default_fmt.setForeground(QColor(theme.text_color)) 
        self.calendar.setDateTextFormat(QDate(), default_fmt)
        
        norm = QTextCharFormat(); norm.setForeground(QColor(theme.text_color))
        wknd = QTextCharFormat(); wknd.setForeground(QColor(theme.weekend_color)) 
        
        hdr_norm = QTextCharFormat(); hdr_norm.setForeground(QColor(theme.text_color))
        hdr_red = QTextCharFormat(); hdr_red.setForeground(QColor(theme.weekend_color))

        for wd in (Qt.Monday, Qt.Tuesday, Qt.Wednesday, Qt.Thursday, Qt.Friday):
            self.calendar.setWeekdayTextFormat(wd, hdr_norm)
        self.calendar.setWeekdayTextFormat(Qt.Saturday, hdr_red)
        self.calendar.setWeekdayTextFormat(Qt.Sunday, hdr_red)

        today = QDate.currentDate()
        today_fmt = QTextCharFormat()
        today_fmt.setBackground(QColor(theme.accent_color))
        today_fmt.setFontWeight(QFont.Bold)
        if today.dayOfWeek() >= 6: today_fmt.setForeground(wknd.foreground())
        else: today_fmt.setForeground(QColor("white")) 

        y, m = self.calendar.yearShown(), self.calendar.monthShown()
        d = QDate(y, m, 1)
        for i in range(d.daysInMonth()):
            current_date = d.addDays(i)
            if current_date == today:
                self.calendar.setDateTextFormat(current_date, today_fmt)
            elif current_date.dayOfWeek() >= 6:
                self.calendar.setDateTextFormat(current_date, wknd)
            else:
                self.calendar.setDateTextFormat(current_date, norm)

        event_dates = set()
        for ev in self.events:
            try:
                dd = datetime.strptime(ev.date, "%Y-%m-%d").date()
                event_dates.add(QDate(dd.year, dd.month, dd.day))
            except ValueError:
                pass
        for task in self.tasks:
            try:
                dd = datetime.strptime(task.due_date, "%Y-%m-%d").date()
                event_dates.add(QDate(dd.year, dd.month, dd.day))
            except ValueError:
                pass
        self.calendar.set_event_dates(event_dates)

    def refresh_events(self):
        self.events = self.data_manager.load_events()
        self.tasks = self.data_manager.load_tasks()
        self.update_calendar_highlights()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        theme = self.data_manager.load_settings().theme
        bg_color = hex_to_rgba(theme.bg_color, 220)
        border_color = hex_to_rgba(theme.border_color, 180)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 18, 18)
        painter.fillPath(path, bg_color)
        pen = QPen(border_color)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPath(path)

class StatisticsWindow(DraggableResizableWindow):
    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.setWindowTitle("📊 資料統計")
        self.setMinimumSize(600, 700)
        self.resize(750, 800)
        self.current_date = QDate.currentDate()
        self._build_ui()
        self.refresh_data()
        self._apply_responsive_typography()
        self.data_manager.restore_window_geometry("statistics_window", self)

    def closeEvent(self, event):
        self.data_manager.save_window_geometry("statistics_window", self)
        super().closeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        theme = self.data_manager.load_settings().theme
        bg_color = hex_to_rgba(theme.bg_color, 255) # 統計視窗不透明
        border_color = hex_to_rgba(theme.border_color, 255)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 18, 18)
        p.fillPath(path, bg_color)
        pen = QPen(border_color)
        pen.setWidth(2)
        p.setPen(pen)
        p.drawPath(path)

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 24, 24, 24)
        title_bar_layout = QHBoxLayout()
        self.title_label = QLabel("📊 資料統計")
        self.title_label.setAlignment(Qt.AlignCenter)
        spacer_left = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        spacer_right = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.close_btn = QPushButton("✖")
        self.close_btn.setFixedSize(32, 32)
        self.close_btn.clicked.connect(self.close)
        title_bar_layout.addSpacerItem(spacer_left)
        title_bar_layout.addWidget(self.title_label)
        title_bar_layout.addSpacerItem(spacer_right)
        title_bar_layout.addWidget(self.close_btn)

        month_selector_layout = QHBoxLayout()
        self.prev_month_btn = QPushButton("◀")
        self.month_label = QLabel()
        self.month_label.setAlignment(Qt.AlignCenter)
        self.month_label.setObjectName("statusLabel")
        self.next_month_btn = QPushButton("▶")
        self.picker_btn = QPushButton("📅 選擇月份")
        self.today_month_btn = QPushButton("本月")
        self.prev_month_btn.clicked.connect(self.go_to_prev_month)
        self.next_month_btn.clicked.connect(self.go_to_next_month)
        self.picker_btn.clicked.connect(self.show_month_picker)
        self.today_month_btn.clicked.connect(self.go_to_current_month)
        month_selector_layout.addWidget(self.prev_month_btn)
        month_selector_layout.addWidget(self.month_label, 1)
        month_selector_layout.addWidget(self.next_month_btn)
        month_selector_layout.addWidget(self.today_month_btn)
        month_selector_layout.addWidget(self.picker_btn)
        self.export_all_btn = QPushButton("匯出全部")
        self.export_all_btn.clicked.connect(lambda: self.export_statistics(scope="all"))
        self.export_month_btn = QPushButton("匯出此月")
        self.export_month_btn.clicked.connect(lambda: self.export_statistics(scope="month"))
        month_selector_layout.addWidget(self.export_all_btn)
        month_selector_layout.addWidget(self.export_month_btn)
        
        self.tabs = QTabWidget()
        work_tab = QWidget()
        work_layout = QVBoxLayout(work_tab)
        self.work_tree = QTreeWidget()
        self.work_tree.setHeaderLabels(["日期", "總工時"])
        self.work_tree.setColumnWidth(0,230)
        summary_group = QGroupBox("本月總結")
        summary_layout = QFormLayout(summary_group)
        self.total_hours_label = QLabel("0.00 小時")
        self.work_days_label = QLabel("0 天")
        summary_layout.addRow("總工時:", self.total_hours_label)
        summary_layout.addRow("總工作日數:", self.work_days_label)
        work_layout.addWidget(self.work_tree)
        work_layout.addWidget(summary_group)

        events_tab = QWidget()
        events_layout = QVBoxLayout(events_tab)
        self.events_tree = QTreeWidget()
        self.events_tree.setHeaderLabels(["日期 / 時間", "標題 / 描述"])
        self.events_tree.setColumnWidth(0, 230)
        events_layout.addWidget(self.events_tree)

        # 任务统计标签页
        tasks_tab = QWidget()
        tasks_layout = QVBoxLayout(tasks_tab)
        self.tasks_tree = QTreeWidget()
        self.tasks_tree.setHeaderLabels(["創建日期", "專案", "標題", "交件日期", "完成度%", "總價"])
        self.tasks_tree.setColumnWidth(0, 180)  # 創建日期，增加寬度以顯示完整日期
        self.tasks_tree.setColumnWidth(1, 140)
        self.tasks_tree.setColumnWidth(2, 170)
        self.tasks_tree.setColumnWidth(3, 190)  # 交件日期，增加寬度以顯示完整日期
        self.tasks_tree.setColumnWidth(4, 120)  # 完成度%，增加寬度以顯示完整標題
        header = self.tasks_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        header.setMinimumSectionSize(90)

        # 本月總結
        tasks_summary_group = QGroupBox("本月總結")
        tasks_summary_group.setMaximumHeight(250)  # 設定本月總結區塊的最大高度
        tasks_summary_layout = QVBoxLayout(tasks_summary_group)
        tasks_summary_layout.setContentsMargins(10, 10, 10, 10)

        summary_scroll = QScrollArea()
        summary_scroll.setWidgetResizable(True)
        summary_scroll.setFrameShape(QFrame.NoFrame)
        summary_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 捲軸區域會自動適應 tasks_summary_group 的高度

        summary_content = QWidget()
        summary_content_layout = QVBoxLayout(summary_content)
        summary_content_layout.setContentsMargins(0, 0, 0, 0)
        summary_content_layout.setSpacing(6)

        # 各專案統計
        self.project_stats_label = QLabel()
        self.project_stats_label.setWordWrap(True)
        summary_content_layout.addWidget(QLabel("📊 各專案統計:"))
        summary_content_layout.addWidget(self.project_stats_label)

        # 總計
        self.all_tasks_stats_label = QLabel()
        summary_content_layout.addWidget(QLabel("📊 總計:"))
        summary_content_layout.addWidget(self.all_tasks_stats_label)
        summary_content_layout.addStretch()

        summary_scroll.setWidget(summary_content)
        tasks_summary_layout.addWidget(summary_scroll)

        tasks_layout.addWidget(self.tasks_tree)
        tasks_layout.addWidget(tasks_summary_group)

        self.tabs.addTab(work_tab, "工時統計")
        self.tabs.addTab(events_tab, "行程總覽")
        self.tabs.addTab(tasks_tab, "任務統計")
        root_layout.addLayout(title_bar_layout)
        root_layout.addLayout(month_selector_layout)
        root_layout.addWidget(self.tabs, 1)
        
        # 設置右鍵菜單策略
        self.work_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.work_tree.customContextMenuRequested.connect(self._show_work_context_menu)
        self.events_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.events_tree.customContextMenuRequested.connect(self._show_events_context_menu)
        self.tasks_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tasks_tree.customContextMenuRequested.connect(self._show_tasks_context_menu)

        # 設置雙擊事件
        self.work_tree.itemDoubleClicked.connect(self._edit_work_item)
        self.events_tree.itemDoubleClicked.connect(self._edit_event_item)
        self.tasks_tree.itemDoubleClicked.connect(self._edit_task_item)

        self.update_style() # 套用樣式
        self.close_btn.setObjectName("closeButton")
        self.setObjectName("statsRoot")

    def update_style(self):
        theme = self.data_manager.load_settings().theme
        self.title_label.setStyleSheet(f"color: {theme.text_color}; font-weight: bold; font-size: 20px; background: transparent; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif;")
        self.setStyleSheet(f"""
            #statsRoot {{ background: transparent; }}
            QTabWidget::pane {{ background-color: {theme.bg_color}; border: 2px solid {theme.border_color}; border-top: none; border-bottom-left-radius: 12px; border-bottom-right-radius: 12px; }}
            QTabBar::tab {{ padding: 10px 18px; font-weight: 700; border: 2px solid {theme.border_color}; border-bottom: none; border-top-left-radius: 10px; border-top-right-radius: 10px; background: {theme.btn_color}; color: {theme.text_color}; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif; }}
            QTabBar::tab:selected {{ background: {theme.bg_color}; }}
            QTreeWidget {{ border: 2px solid {theme.border_color}; border-radius: 12px; padding: 5px; background-color: white; color: {theme.text_color}; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif; }}
            QHeaderView::section {{ background-color: {theme.btn_color}; padding: 4px; border: 1px solid {theme.border_color}; font-weight: bold; color: {theme.text_color}; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif; }}
            QPushButton#closeButton {{ font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif; font-weight: bold; background-color: rgba(230, 120, 120, 150); border-radius: 16px; padding: 0; }}
            QPushButton#closeButton:hover {{ background-color: rgba(255, 0, 0, 180); }}
            QLabel {{ color: {theme.text_color}; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif; }}
            QGroupBox {{ border: 2px solid {theme.border_color}; border-radius: 14px; margin-top: 10px; padding: 12px; font-weight: 800; color: {theme.text_color}; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
            QPushButton {{ background-color: {theme.btn_color}; color: {theme.text_color}; border: 2px solid {theme.border_color}; border-radius: 12px; padding: 8px 16px; font-weight: 700; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif; }}
            QPushButton:hover {{ background-color: {theme.btn_hover}; }}
        """)

    def show_month_picker(self):
        menu = QMenu(self)
        calendar = QCalendarWidget()
        calendar.setGridVisible(True)
        calendar.setCurrentPage(self.current_date.year(), self.current_date.month())
        action = QWidgetAction(self)
        action.setDefaultWidget(calendar)
        menu.addAction(action)
        calendar.clicked.connect(lambda date: (self.date_picked_from_popup(date), menu.close()))
        menu.exec(self.picker_btn.mapToGlobal(QPoint(0, self.picker_btn.height())))

    def date_picked_from_popup(self, date):
        self.current_date = date
        self.populate_ui_for_month()

    def refresh_data(self):
        self.events = self.data_manager.load_events()
        self.work_records = self.data_manager.load_work_records()
        self.tasks = self.data_manager.load_tasks()
        self.populate_ui_for_month()
        
    def populate_ui_for_month(self):
        self.work_tree.clear()
        self.events_tree.clear()
        self.tasks_tree.clear()
        self.month_label.setText(self.current_date.toString("yyyy 年 MM 月"))
        year = self.current_date.year()
        month = self.current_date.month()

        monthly_events = [e for e in self.events if datetime.strptime(e.date, "%Y-%m-%d").month == month and datetime.strptime(e.date, "%Y-%m-%d").year == year]
        monthly_work = {k: v for k, v in self.work_records.items() if datetime.strptime(k, "%Y-%m-%d").month == month and datetime.strptime(k, "%Y-%m-%d").year == year}

        total_monthly_hours = 0
        for date_str in sorted(monthly_work.keys()):
            record = monthly_work[date_str]
            hours = record.calculate_total_hours()
            total_monthly_hours += hours
            item = QTreeWidgetItem(self.work_tree, [date_str, f"{hours:.2f} 小時"])
            item.setData(0, Qt.UserRole, date_str)  # 儲存日期
        self.total_hours_label.setText(f"{total_monthly_hours:.2f} 小時")
        self.work_days_label.setText(f"{len(monthly_work)} 天")

        monthly_events.sort(key=lambda x: f"{x.date} {x.time}")
        for event in monthly_events:
            date_item = QTreeWidgetItem(self.events_tree, [event.date, event.title])
            date_item.setData(0, Qt.UserRole, event.id)  # 儲存事件ID
            child_item = QTreeWidgetItem(date_item, [f"  └ {event.time}", event.description])
            child_item.setData(0, Qt.UserRole, event.id)  # 子項目也儲存事件ID
        self.events_tree.expandAll()

        # 任務統計
        monthly_tasks = [
            t for t in self.tasks
            if datetime.strptime(t.created_date, "%Y-%m-%d").month == month
            and datetime.strptime(t.created_date, "%Y-%m-%d").year == year
        ]

        # 按專案和幣別統計
        project_stats = {}  # {project_name: {currency: {'count': n, 'price': p}}}
        currency_totals = {}  # {currency: {'count': n, 'price': p}}
        total_tasks_count = len(monthly_tasks)

        for task in monthly_tasks:
            total_price = task.get_total_price()
            currency = getattr(task, 'currency', 'NTD')

            # 添加到樹形控件（顯示帶幣別的價格）
            completion_str = f"{task.completion}%"
            price_str = f"{currency} ${total_price:,.2f}"
            task_item = QTreeWidgetItem(self.tasks_tree, [
                task.created_date,
                task.project_name,
                task.title,
                f"{task.due_date} {task.due_time}",
                completion_str,
                price_str
            ])
            task_item.setData(0, Qt.UserRole, task.id)  # 儲存任務ID

            # 如果超期且未完成，標紅
            if task.is_overdue():
                for i in range(6):
                    task_item.setForeground(i, QColor("red"))
                font = task_item.font(0)
                font.setBold(True)
                for i in range(6):
                    task_item.setFont(i, font)

            # 統計專案數據（按幣別分開）
            if task.project_name not in project_stats:
                project_stats[task.project_name] = {}
            if currency not in project_stats[task.project_name]:
                project_stats[task.project_name][currency] = {'count': 0, 'price': 0.0}
            project_stats[task.project_name][currency]['count'] += 1
            project_stats[task.project_name][currency]['price'] += total_price

            # 統計各幣別總計
            if currency not in currency_totals:
                currency_totals[currency] = {'count': 0, 'price': 0.0}
            currency_totals[currency]['count'] += 1
            currency_totals[currency]['price'] += total_price

        # 更新專案統計標籤（按幣別分開顯示）
        if project_stats:
            project_text = ""
            for project, currencies in sorted(project_stats.items()):
                project_text += f"📁 {project}:\n"
                for currency, stats in sorted(currencies.items()):
                    project_text += f"   • {currency}: {stats['count']} 個任務, ${stats['price']:,.2f}\n"
            self.project_stats_label.setText(project_text.strip())
        else:
            self.project_stats_label.setText("本月無任務")

        # 更新總計標籤（按幣別分開顯示）
        total_text = f"總任務數: {total_tasks_count} 個\n總價值:\n"
        if currency_totals:
            for currency, stats in sorted(currency_totals.items()):
                total_text += f"  • {currency}: ${stats['price']:,.2f}\n"
        else:
            total_text += "  無價格資料"
        self.all_tasks_stats_label.setText(total_text.strip())

        self.tasks_tree.expandAll()

    def _gather_monthly_tasks(self):
        year = self.current_date.year()
        month = self.current_date.month()
        return [
            t for t in self.tasks
            if datetime.strptime(t.created_date, "%Y-%m-%d").month == month
            and datetime.strptime(t.created_date, "%Y-%m-%d").year == year
        ]

    def export_statistics(self, scope="month"):
        # scope: "month" (current month) or "all"
        is_month_only = scope == "month"
        current_year = self.current_date.year()
        current_month = self.current_date.month()

        def in_scope(date_str):
            if not is_month_only:
                return True
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                return dt.year == current_year and dt.month == current_month
            except ValueError:
                return False

        # Prepare data
        work_rows = []
        for date_str, record in (self.work_records or {}).items():
            if not in_scope(date_str):
                continue
            for session in record.sessions:
                start = session.get("start", "")
                end = session.get("end", "")
                duration_min = ""
                if start and end:
                    try:
                        sd = datetime.fromisoformat(start)
                        ed = datetime.fromisoformat(end)
                        duration_min = f"{(ed - sd).total_seconds() / 60:.1f}"
                    except Exception:
                        duration_min = ""
                work_rows.append([date_str, start, end, duration_min])

        event_rows = []
        for ev in self.events:
            if not in_scope(ev.date):
                continue
            event_rows.append([
                ev.date,
                ev.time,
                ev.title,
                ev.description,
                "是" if ev.completed else "否"
            ])

        task_rows = []
        for task in self.tasks:
            if not in_scope(task.created_date):
                continue
            price_items_str = "; ".join(
                f"{pi.get('name','')}(單價:{pi.get('unit_price',0)},數量:{pi.get('quantity',0)})"
                for pi in task.price_items
            )
            task_rows.append([
                task.created_date,
                task.project_name,
                task.title,
                task.due_date,
                task.due_time,
                f"{task.completion}%",
                task.client,
                task.description,
                task.remind_before,
                f"{task.get_total_price():.2f}",
                price_items_str
            ])

        if not (work_rows or event_rows or task_rows):
            QMessageBox.information(self, "提示", "沒有資料可匯出。")
            return

        default_name = "全部統計" if scope == "all" else "當月統計"
        path, _ = QFileDialog.getSaveFileName(
            self, "匯出統計", f"{default_name}.xlsx",
            "Excel 檔案 (*.xlsx);;CSV 檔案 (*.csv)"
        )
        if not path:
            return

        try:
            if path.lower().endswith(".xlsx"):
                try:
                    from openpyxl import Workbook
                except ImportError:
                    QMessageBox.warning(self, "錯誤", "缺少 openpyxl 套件，請改存為 CSV 或先安裝 openpyxl。")
                    return
                wb = Workbook()
                # 工時
                ws = wb.active
                ws.title = "工時"
                ws.append(["日期", "開始", "結束", "時長(分鐘)"])
                for row in work_rows:
                    ws.append(row)
                # 行程
                ws_events = wb.create_sheet("行程")
                ws_events.append(["日期", "時間", "標題", "描述", "已完成"])
                for row in event_rows:
                    ws_events.append(row)
                # 任務
                ws_tasks = wb.create_sheet("任務")
                ws_tasks.append(["創建日期", "專案", "標題", "交件日期", "交件時間", "完成度", "客戶", "描述", "提醒(分鐘)", "總價", "價格項目"])
                for row in task_rows:
                    ws_tasks.append(row)
                wb.save(path)
            else:
                if not path.lower().endswith(".csv"):
                    path += ".csv"
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["類型", "日期", "時間", "標題/專案", "明細", "備註"])
                    for r in work_rows:
                        writer.writerow(["工時", r[0], "", f"{r[1]}~{r[2]}", f"時長(分):{r[3]}", ""])
                    for r in event_rows:
                        writer.writerow(["行程", r[0], r[1], r[2], r[3], f"已完成:{r[4]}"])
                    for r in task_rows:
                        writer.writerow(["任務", r[0], r[3], f"{r[1]}-{r[2]}", f"交件:{r[3]} {r[4]} 完成度:{r[5]} 總價:{r[9]}", f"客戶:{r[6]} 描述:{r[7]} 價格:{r[10]} 提醒:{r[8]}分"])
            QMessageBox.information(self, "提示", "匯出完成！")
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"匯出失敗：{e}")

    def go_to_prev_month(self):
        self.current_date = self.current_date.addMonths(-1)
        self.populate_ui_for_month()

    def go_to_next_month(self):
        self.current_date = self.current_date.addMonths(1)
        self.populate_ui_for_month()
    
    def go_to_current_month(self):
        self.current_date = QDate.currentDate()
        self.populate_ui_for_month()

    def showEvent(self, event):
        self.update_style() # 開啟時更新主題
        self.refresh_data()
        super().showEvent(event)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_responsive_typography()

    def _apply_responsive_typography(self):
        base = max(16, int(min(self.width(), self.height()) * 0.022))
        group_px = int(base * 1.1)
        btn_px   = int(base * 1.0)
        label_px = int(base * 0.95)
        status_label_px = int(base * 1.15)
        title_px = int(base * 1.6)
        list_px = int(base * 1.0)
        theme = self.data_manager.load_settings().theme

        def set_px(w, px, bold=False):
            f = w.font()
            f.setFamily(theme.font_family)
            f.setPixelSize(px)
            f.setBold(theme.font_bold or bold)
            f.setItalic(theme.font_italic)
            f.setUnderline(theme.font_underline)
            f.setStrikeOut(theme.font_strikeout)
            if not bold:
                f.setWeight(QFont.Weight(theme.font_weight))
            w.setFont(f)

        for w in self.findChildren(QLabel, "pageTitle"): set_px(w, title_px, True)
        for lab in self.findChildren(QLabel):
            if lab.objectName() == "statusLabel": set_px(lab, status_label_px)
            elif lab is not getattr(self, 'title_label', None): set_px(lab, label_px)
        for btn in self.findChildren(QPushButton): set_px(btn, btn_px, True)
        for tree in self.findChildren(QTreeWidget):
            set_px(tree, list_px)
            header_font = QFont(theme.font_family, btn_px, QFont.Bold)
            header_font.setItalic(theme.font_italic)
            header_font.setUnderline(theme.font_underline)
            header_font.setStrikeOut(theme.font_strikeout)
            tree.header().setFont(header_font)
        tab_bar = self.tabs.tabBar()
        tf = tab_bar.font()
        tf.setFamily(theme.font_family)
        tf.setPixelSize(group_px)
        tf.setBold(theme.font_bold)
        tf.setItalic(theme.font_italic)
        tf.setUnderline(theme.font_underline)
        tf.setStrikeOut(theme.font_strikeout)
        tf.setWeight(QFont.Weight(theme.font_weight))
        tab_bar.setFont(tf)

    # ========== 事件編輯和刪除方法 ==========
    def _edit_event_item(self, item, column):
        """雙擊編輯事件"""
        event_id = item.data(0, Qt.UserRole)
        if not event_id:
            return

        # 從所有事件中找到對應的事件
        all_events = self.data_manager.load_events()
        event_to_edit = next((e for e in all_events if e.id == event_id), None)

        if not event_to_edit:
            QMessageBox.warning(self, "錯誤", "找不到要編輯的行程！")
            return

        # 開啟編輯對話框（EventEditDialog 會直接修改 event_to_edit 物件）
        dialog = EventEditDialog(self.data_manager, event_to_edit, self)
        if dialog.exec() == QDialog.Accepted:
            # 儲存變更
            self.data_manager.save_events(all_events)
            self.refresh_data()

            # 通知主視窗更新相關視圖
            if self.parent():
                # 更新總覽的今日行程
                if hasattr(self.parent(), 'refresh_overview_events'):
                    self.parent().refresh_overview_events()
                # 更新行程分頁
                if hasattr(self.parent(), 'event_page'):
                    self.parent().event_page.events = self.data_manager.load_events()
                    self.parent().event_page.update_event_list()
                # 更新日曆視窗
                if hasattr(self.parent(), 'calendar_window'):
                    if self.parent().calendar_window and self.parent().calendar_window.isVisible():
                        self.parent().calendar_window.events = self.data_manager.load_events()
                        self.parent().calendar_window.update_calendar_highlights()

            QMessageBox.information(self, "成功", "行程已更新！")

    def _show_events_context_menu(self, position):
        """顯示事件右鍵菜單"""
        item = self.events_tree.itemAt(position)
        if not item:
            return

        event_id = item.data(0, Qt.UserRole)
        if not event_id:
            return

        menu = QMenu(self)
        delete_action = menu.addAction("刪除選中項目")

        action = menu.exec(self.events_tree.viewport().mapToGlobal(position))

        if action == delete_action:
            self._delete_event_item(event_id)

    def _delete_event_item(self, event_id):
        """刪除事件"""
        reply = QMessageBox.question(
            self, "確認刪除",
            "確定要刪除這個行程嗎？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            all_events = self.data_manager.load_events()
            all_events = [e for e in all_events if e.id != event_id]
            self.data_manager.save_events(all_events)
            self.refresh_data()
            QMessageBox.information(self, "成功", "行程已刪除！")

    # ========== 任務編輯和刪除方法 ==========
    def _edit_task_item(self, item, column):
        """雙擊編輯任務"""
        task_id = item.data(0, Qt.UserRole)
        if not task_id:
            return

        # 從所有任務中找到對應的任務
        all_tasks = self.data_manager.load_tasks()
        task_to_edit = next((t for t in all_tasks if t.id == task_id), None)

        if not task_to_edit:
            QMessageBox.warning(self, "錯誤", "找不到要編輯的任務！")
            return

        # 開啟編輯對話框
        dialog = TaskEditDialog(self.data_manager, task_to_edit, self)
        if dialog.exec() == QDialog.Accepted:
            # 取得更新後的資料並更新任務物件
            task_data = dialog.get_task_data()
            if task_data:
                task_to_edit.project_name = task_data['project_name']
                task_to_edit.title = task_data['title']
                task_to_edit.due_date = task_data['due_date']
                task_to_edit.due_time = task_data['due_time']
                task_to_edit.client = task_data['client']
                task_to_edit.currency = task_data['currency']
                task_to_edit.description = task_data['description']
                task_to_edit.completion = task_data['completion']
                task_to_edit.price_items = task_data['price_items']
                task_to_edit.remind_before = task_data['remind_before']

                # 儲存變更
                self.data_manager.save_tasks(all_tasks)
                self.refresh_data()

                # 通知主視窗更新
                if self.parent() and hasattr(self.parent(), 'refresh_tasks'):
                    self.parent().refresh_tasks()
                if self.parent() and hasattr(self.parent(), 'task_page'):
                    self.parent().task_page.tasks = self.data_manager.load_tasks()
                    self.parent().task_page.update_task_list()

                QMessageBox.information(self, "成功", "任務已更新！")

    def _show_tasks_context_menu(self, position):
        """顯示任務右鍵菜單"""
        item = self.tasks_tree.itemAt(position)
        if not item:
            return

        task_id = item.data(0, Qt.UserRole)
        if not task_id:
            return

        menu = QMenu(self)
        delete_action = menu.addAction("刪除選中項目")

        action = menu.exec(self.tasks_tree.viewport().mapToGlobal(position))

        if action == delete_action:
            self._delete_task_item(task_id)

    def _delete_task_item(self, task_id):
        """刪除任務"""
        reply = QMessageBox.question(
            self, "確認刪除",
            "確定要刪除這個任務嗎？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            all_tasks = self.data_manager.load_tasks()
            all_tasks = [t for t in all_tasks if t.id != task_id]
            self.data_manager.save_tasks(all_tasks)
            self.refresh_data()
            QMessageBox.information(self, "成功", "任務已刪除！")

    # ========== 工時編輯和刪除方法 ==========
    def _edit_work_item(self, item, column):
        """雙擊編輯工時記錄"""
        date_str = item.data(0, Qt.UserRole)
        if not date_str:
            return

        # 載入工時記錄
        work_records = self.data_manager.load_work_records()
        record = work_records.get(date_str)

        if not record:
            QMessageBox.warning(self, "錯誤", "找不到要編輯的工時記錄！")
            return

        # 開啟編輯對話框
        dialog = WorkSessionEditDialog(self.data_manager, date_str, record.sessions.copy(), self)
        if dialog.exec() == QDialog.Accepted:
            # 更新工時記錄
            record.sessions = dialog.get_sessions()
            work_records[date_str] = record
            self.data_manager.save_work_records(work_records)
            self.refresh_data()

            # 通知主視窗更新打卡分頁
            if self.parent() and hasattr(self.parent(), 'work_page'):
                self.parent().work_page._refresh_ui_states()

            QMessageBox.information(self, "成功", "工時記錄已更新！")

    def _show_work_context_menu(self, position):
        """顯示工時右鍵菜單"""
        item = self.work_tree.itemAt(position)
        if not item:
            return

        date_str = item.data(0, Qt.UserRole)
        if not date_str:
            return

        menu = QMenu(self)
        delete_action = menu.addAction("刪除選中項目")

        action = menu.exec(self.work_tree.viewport().mapToGlobal(position))

        if action == delete_action:
            self._delete_work_item(date_str)

    def _delete_work_item(self, date_str):
        """刪除工時記錄"""
        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要刪除 {date_str} 的所有工時記錄嗎？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            work_records = self.data_manager.load_work_records()
            if date_str in work_records:
                del work_records[date_str]
                self.data_manager.save_work_records(work_records)
                self.refresh_data()
                QMessageBox.information(self, "成功", "工時記錄已刪除！")

class AppearancePage(QWidget):
    def __init__(self, data_manager, on_apply_theme=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.on_apply_theme = on_apply_theme
        self.theme = self.data_manager.load_settings().theme
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignTop)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        title = QLabel("🎨 外觀設定")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        # 顏色設定群組
        color_group = QGroupBox("配色設定")
        grid = QGridLayout(color_group)
        grid.setHorizontalSpacing(10)  # 標籤和按鈕之間的間距
        grid.setVerticalSpacing(12)    # 垂直間距
        grid.setColumnStretch(1, 1)    # 第1欄（左側按鈕）可拉伸
        grid.setColumnStretch(4, 1)    # 第4欄（右側按鈕）可拉伸
        grid.setColumnMinimumWidth(2, 30)  # 第2欄最小寬度，作為左右兩組的間隔
        
        # 輔助：建立顏色選擇按鈕的函式
        def create_color_picker(label_text, attr_name, row, col):
            label = QLabel(label_text)
            btn = QPushButton()
            btn.setMinimumWidth(60)
            btn.setFixedHeight(30)
            current_color = getattr(self.theme, attr_name)
            btn.setStyleSheet(f"background-color: {current_color}; border: 1px solid #999;")
            btn.clicked.connect(lambda: self.pick_color(attr_name, btn))
            
            grid.addWidget(label, row, col)
            grid.addWidget(btn, row, col+1)

        # 左側兩欄（第0, 1欄）
        create_color_picker("背景顏色", "bg_color", 0, 0)
        create_color_picker("按鈕背景", "btn_color", 1, 0)
        create_color_picker("邊框顏色", "border_color", 2, 0)
        create_color_picker("週末顏色", "weekend_color", 3, 0)
        create_color_picker("行程高亮", "event_highlight_color", 4, 0)
        
        # 右側兩欄（第3, 4欄）
        create_color_picker("文字顏色", "text_color", 0, 3)
        create_color_picker("按鈕懸停", "btn_hover", 1, 3)
        create_color_picker("強調色", "accent_color", 2, 3)
        create_color_picker("非本月日期", "other_month_color", 3, 3)

        root.addWidget(color_group)

        # 字體設定群組
        font_group = QGroupBox("字體設定")
        f_layout = QHBoxLayout(font_group)

        styles = []
        if self.theme.font_bold:
            styles.append("粗體")
        if self.theme.font_italic:
            styles.append("斜體")
        if self.theme.font_underline:
            styles.append("底線")
        if self.theme.font_strikeout:
            styles.append("刪除線")
        style_text = ", ".join(styles) if styles else "標準"

        self.font_btn = QPushButton(f"選擇字體 ({self.theme.font_family} - {style_text})")
        self.font_btn.clicked.connect(self.pick_font)
        f_layout.addWidget(self.font_btn)

        root.addWidget(font_group)

        # 操作按鈕
        btn_layout = QHBoxLayout()
        btn_apply = QPushButton("套用設定")
        btn_apply.clicked.connect(self.apply_changes)
        btn_reset = QPushButton("恢復預設值")
        btn_reset.clicked.connect(self.reset_theme)
        btn_export = QPushButton("匯出配色")
        btn_export.clicked.connect(self.export_theme)
        btn_import = QPushButton("匯入配色")
        btn_import.clicked.connect(self.import_theme)
        
        btn_layout.addWidget(btn_apply)
        btn_layout.addWidget(btn_reset)
        btn_layout.addWidget(btn_export)
        btn_layout.addWidget(btn_import)
        root.addLayout(btn_layout)
        root.addStretch()

    def pick_color(self, attr_name, btn):
        current_color = QColor(getattr(self.theme, attr_name))
        color = QColorDialog.getColor(current_color, self, "選擇顏色")
        if color.isValid():
            hex_color = color.name().upper()
            setattr(self.theme, attr_name, hex_color)
            btn.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #999;")

    def pick_font(self):
        current_font = QFont(self.theme.font_family)
        current_font.setBold(self.theme.font_bold)
        current_font.setItalic(self.theme.font_italic)
        current_font.setUnderline(self.theme.font_underline)
        current_font.setStrikeOut(self.theme.font_strikeout)
        current_font.setWeight(QFont.Weight(self.theme.font_weight))

        ok, font = QFontDialog.getFont(current_font, self, "選擇字體")
        if ok:
            self.theme.font_family = font.family()
            self.theme.font_bold = font.bold()
            self.theme.font_italic = font.italic()
            self.theme.font_underline = font.underline()
            self.theme.font_strikeout = font.strikeOut()
            self.theme.font_weight = font.weight()

            styles = []
            if font.bold():
                styles.append("粗體")
            if font.italic():
                styles.append("斜體")
            if font.underline():
                styles.append("底線")
            if font.strikeOut():
                styles.append("刪除線")

            style_text = ", ".join(styles) if styles else "標準"
            self.font_btn.setText(f"選擇字體 ({font.family()} - {style_text})")

    def apply_changes(self):
        settings = self.data_manager.load_settings()
        settings.theme = self.theme
        self.data_manager.save_settings(settings)
        if self.on_apply_theme:
            self.on_apply_theme()
        QMessageBox.information(self, "提示", "外觀設定已套用")

    def export_theme(self):
        path, _ = QFileDialog.getSaveFileName(self, "匯出配色", "", "JSON 檔案 (*.json)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.theme), f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "提示", "配色已匯出")

    def import_theme(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入配色", "", "JSON 檔案 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.theme = ThemeConfig(**data)
            settings = self.data_manager.load_settings()
            settings.theme = self.theme
            self.data_manager.save_settings(settings)
            self._rebuild_ui()
            if self.on_apply_theme:
                self.on_apply_theme()
            QMessageBox.information(self, "提示", "配色已匯入並套用")
        except Exception as e:
            QMessageBox.warning(self, "錯誤", f"匯入失敗：{e}")

    def reset_theme(self):
        if QMessageBox.question(self, "確認", "確定要恢復為預設配色嗎？") == QMessageBox.Yes:
            self.theme = ThemeConfig()
            settings = self.data_manager.load_settings()
            settings.theme = self.theme
            self.data_manager.save_settings(settings)
            self._rebuild_ui()
            if self.on_apply_theme:
                self.on_apply_theme()

    def _rebuild_ui(self):
        old_layout = self.layout()
        if old_layout:
            self._clear_layout(old_layout)
            QWidget().setLayout(old_layout)
        self._build_ui()

    def _clear_layout(self, layout):
        """遞歸清除布局中的所有子部件"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

class TabbedMainWindow(QMainWindow):
    def __init__(self, tray_icon=None):
        super().__init__()
        self.data_manager = DataManager()
        self.tray_icon = tray_icon
        self.setWindowTitle("CocoTimer")
        self.setMinimumSize(560, 800)
        self.resize(780, 900)
        self.settings = self.data_manager.load_settings()
        self.events = self.data_manager.load_events()
        self.work_records = self.data_manager.load_work_records()
        self.clock_window = None
        self.calendar_window = None
        self.stats_window = None
        self.pomodoro_float_window = None
        self.work_time_float_window = None
        self.active_toasts = []
        
        self.reminder_windows = [] 

        self.notification_timer = QTimer(self); self.notification_timer.timeout.connect(self.check_notifications)
        self.notification_timer.start(1000) 

        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.timeout.connect(self.update_work_status_label)
        self.ui_update_timer.start(1000)

        self.last_known_date = QDate.currentDate()
        self.date_check_timer = QTimer(self)
        self.date_check_timer.timeout.connect(self._check_for_date_change)
        self.date_check_timer.start(30000)

        self.water_timer = QTimer(self); self.water_timer.timeout.connect(self.water_reminder)
        if self.settings.water_reminder_enabled:
            self.water_timer.start(self.settings.water_reminder_interval * 60000)
        self.water_sound = QSoundEffect(self)
        self.water_sound.setSource(QUrl.fromLocalFile(resource_path("sounds/water_alert.wav")))
        self.water_sound.setVolume(self.settings.volume)
        
        self.notification_sound = QSoundEffect(self)
        self.notification_sound.setSource(QUrl.fromLocalFile(resource_path("sounds/pomodoro_alert.wav")))
        self.notification_sound.setVolume(self.settings.volume)
        
        self.pomodoro_state = "idle"
        self.pomodoro_end_time = None
        self.pomodoro_timer = QTimer(self)
        self.pomodoro_timer.timeout.connect(self._update_pomodoro_timer)
        self.pomodoro_display_timer = QTimer(self)
        self.pomodoro_display_timer.timeout.connect(self._update_pomodoro_display)
        self.pomodoro_sound = QSoundEffect(self)
        self.pomodoro_sound.setSource(QUrl.fromLocalFile(resource_path("sounds/pomodoro_alert.wav")))
        self.pomodoro_sound.setVolume(self.settings.volume)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)
        self._apply_tab_theme()

        self._build_overview_tab()

        self.event_page = EventPage(self.data_manager, calendar_window_getter=lambda: self.calendar_window, main_window=self)
        self.task_page = TaskPage(self.data_manager, main_window=self)
        self.work_page = WorkPage(self.data_manager, main_window=self)
        self.settings_page = SettingsPage(self.data_manager, on_settings_saved=self._on_settings_saved)
        # <<< NEW: 加入外觀設定頁面 >>>
        self.appearance_page = AppearancePage(self.data_manager, on_apply_theme=self.apply_theme_globally)

        self.tabs.addTab(self.event_page, "行程")
        self.tabs.addTab(self.task_page, "任務")
        self.tabs.addTab(self.work_page, "打卡")
        self.tabs.addTab(self.settings_page, "設定")
        self.tabs.addTab(self.appearance_page, "外觀")

        central = QWidget()
        central_lay = QVBoxLayout(central)
        central_lay.setContentsMargins(0, 0, 0, 0)
        central_lay.setSpacing(12)
        self.setCentralWidget(central)
        central_lay.addWidget(self.tabs)

        # 版權與創作者資訊（所有分頁底部共用）
        copyright_label = QLabel('Version 2.0 · Created by <a href="https://my-intro-website-production.up.railway.app/" style="color: #666; text-decoration: none;">Coco</a> · © 2025 CocoTimer. All rights reserved.')
        copyright_label.setAlignment(Qt.AlignCenter)
        copyright_label.setOpenExternalLinks(True)
        copyright_label.setTextFormat(Qt.RichText)
        copyright_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        copyright_label.setStyleSheet("color: #888; font-size: 10px; padding: 8px;")
        copyright_label.setContentsMargins(0, 0, 0, 0)
        central_lay.addWidget(copyright_label)

        self.data_manager.restore_window_geometry("main_window", self)
        self._apply_base_theme()
        self._apply_responsive_typography()
        
        self.refresh_overview_events()
        
        self.update_work_status_label()
        self._restore_window_visibility()

    def apply_theme_globally(self):
        """套用新主題到所有視窗"""
        # <<< FIX: 確保主視窗記憶體中的設定也更新，防止 closeEvent 覆蓋 >>>
        self.settings = self.data_manager.load_settings()
        theme = self.settings.theme
        
        # 1. 更新全域字體 (必須在套用樣式表之前)
        app = QApplication.instance()
        dpi = app.primaryScreen().logicalDotsPerInch() or 96
        scale = dpi / 96.0
        base_pt = int(theme.base_font_size * scale)
        app_font = QFont(theme.font_family, base_pt)
        app.setFont(app_font)
        
        # 2. 更新主視窗樣式
        self._apply_base_theme()
        self._apply_tab_theme()
        
        # 3. 強制更新所有子元件的字體
        def update_widget_fonts(widget):
            current_font = widget.font()
            current_font.setFamily(theme.font_family)
            widget.setFont(current_font)
            for child in widget.findChildren(QWidget):
                child_font = child.font()
                child_font.setFamily(theme.font_family)
                child.setFont(child_font)
        
        update_widget_fonts(self)
        
        # 4. 重新套用響應式字體大小
        self._apply_responsive_typography()
        
        # 5. 更新懸浮視窗
        if self.clock_window: self.clock_window.update_style()
        if self.calendar_window: 
            self.calendar_window._apply_calendar_theme()
            self.calendar_window.update_calendar_highlights()
        if self.stats_window: self.stats_window.update_style()
        if self.pomodoro_float_window: self.pomodoro_float_window.update_style()
        if self.work_time_float_window: self.work_time_float_window.update_style()

    def show_toast(self, title, message):
        self.active_toasts = [t for t in self.active_toasts if t.isVisible()]
        toast = ToastNotification(title, message, self)
        screen_rect = QApplication.primaryScreen().availableGeometry()
        toast_rect = toast.rect()
        center_pos = screen_rect.center() - toast_rect.center()
        y_offset = sum(t.height() + 10 for t in self.active_toasts)
        final_pos = QPoint(center_pos.x(), center_pos.y() + y_offset)
        toast.move(final_pos)
        self.active_toasts.append(toast)
        toast.show()

    def _restore_window_visibility(self):
        if self.settings.clock_visible:
            self.toggle_clock(save_state=False)
        if self.settings.calendar_visible:
            self.toggle_calendar(save_state=False)
        if self.settings.pomodoro_float_visible:
            self.toggle_pomodoro_float(save_state=False)
        if self.settings.work_time_float_visible:
            self.toggle_work_time_float(save_state=False)

    def _check_for_date_change(self):
        today = QDate.currentDate()
        if today != self.last_known_date:
            self.last_known_date = today
            self.refresh_overview_events()
            if self.calendar_window and self.calendar_window.isVisible():
                self.calendar_window.refresh_events()
            if hasattr(self, 'work_page'):
                self.work_page._refresh_ui_states()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                self.hide()
                event.ignore()

    def closeEvent(self, e):
        self.settings.clock_visible = bool(self.clock_window and self.clock_window.isVisible())
        self.settings.calendar_visible = bool(self.calendar_window and self.calendar_window.isVisible())
        self.settings.pomodoro_float_visible = bool(self.pomodoro_float_window and self.pomodoro_float_window.isVisible())
        self.settings.work_time_float_visible = bool(self.work_time_float_window and self.work_time_float_window.isVisible())
        self.data_manager.save_settings(self.settings)
        self.data_manager.save_window_geometry("main_window", self)
        if self.clock_window: self.clock_window.close()
        if self.calendar_window: self.calendar_window.close()
        if self.stats_window: self.stats_window.close()
        if self.pomodoro_float_window: self.pomodoro_float_window.close()
        if self.work_time_float_window: self.work_time_float_window.close()
        QApplication.instance().quit()
        e.accept()

    def _apply_base_theme(self):
        # <<< FIX: 從設定讀取主題顏色 >>>
        theme = self.data_manager.load_settings().theme
        
        self.setStyleSheet(f"""
            QWidget {{ background-color: {theme.bg_color}; color: {theme.text_color}; font-family: '{theme.font_family}','Microsoft JhengHei',sans-serif; }}
            QGroupBox {{ border: 2px solid {theme.border_color}; border-radius: 14px; margin-top: 10px; padding: 12px; background: {theme.bg_color}; font-weight: 800; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; }}
            QPushButton {{ background-color: {theme.btn_color}; color: {theme.text_color}; border: 2px solid {theme.border_color}; border-radius: 12px; padding: 12px 16px; font-weight: 700; }}
            QPushButton:hover  {{ background-color: {theme.btn_hover}; }}
            QPushButton:pressed{{ background-color: {theme.border_color}; }}
            QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QComboBox, QTextEdit {{ min-height: 30px; border: 2px solid {theme.border_color}; border-radius: 10px; padding: 4px 8px; background: #FFFFFF; color: {theme.text_color}; }}
            QToolTip {{ background-color: {theme.bg_color}; color: {theme.text_color}; border: 2px solid {theme.border_color}; padding: 6px 8px; border-radius: 8px; }}
            
            QCheckBox {{
                spacing: 8px;
                font-size: 14px;
            }}
            QCheckBox::indicator {{
                width: 20px;
                height: 20px;
                border: 2px solid {theme.accent_color}; 
                background-color: #FFFFFF; 
                border-radius: 4px;
            }}
            QCheckBox::indicator:hover {{
                border-color: {theme.text_color};
            }}
            QCheckBox::indicator:checked {{
                background-color: {theme.accent_color};
                border-color: {theme.accent_color};
                image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIzIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5bGluZSBwb2ludHM9IjIwIDYgOSAxNyA0IDEyIi8+PC9zdmc+);
            }}
        """)

    def _apply_tab_theme(self):
        theme = self.data_manager.load_settings().theme
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; margin: 0; padding: 0; background: {theme.bg_color}; }}
            QTabBar::tab {{ background: {theme.btn_color}; border: 2px solid {theme.border_color}; border-bottom: none; border-top-left-radius: 10px; border-top-right-radius: 10px; padding: 10px 18px; margin-right: 6px; font-weight: 700; color: {theme.text_color}; }}
            QTabBar::tab:selected {{ background: {theme.bg_color}; }}
            QTabBar::tab:hover {{ background: {theme.btn_hover}; }}
        """)
        self.tabs.tabBar().setExpanding(True)

    def _build_overview_tab(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setAlignment(Qt.AlignTop)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(18)
        title = QLabel("🕒 總覽")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)

        display_group = QGroupBox("顯示控制")
        grid = QGridLayout(display_group)
        grid.setSpacing(10)  # 固定按鈕間距
        grid.setVerticalSpacing(12)  # 固定垂直間距
        self.btn_show_clock = QPushButton("顯示數字時鐘")
        self.btn_show_cal   = QPushButton("顯示日曆")
        self.btn_show_stats = QPushButton("📊 顯示統計")
        self.btn_show_clock.clicked.connect(self.toggle_clock)
        self.btn_show_cal.clicked.connect(self.toggle_calendar)
        self.btn_show_stats.clicked.connect(self.show_statistics_window)
        grid.addWidget(self.btn_show_clock, 0, 0)
        grid.addWidget(self.btn_show_cal,   0, 1)
        grid.addWidget(self.btn_show_stats, 1, 0, 1, 2)
        grid.setAlignment(Qt.AlignHCenter)
        v.addWidget(display_group)

        # <<< NEW: 調整順序，懸浮視窗在中間 >>>
        float_group = QGroupBox("懸浮視窗")
        float_grid = QGridLayout(float_group)
        float_grid.setSpacing(10)  # 固定按鈕間距
        self.btn_toggle_pomo_float = QPushButton("顯示番茄鐘倒數")
        self.btn_toggle_work_float = QPushButton("顯示工時計時")
        self.btn_toggle_pomo_float.clicked.connect(self.toggle_pomodoro_float)
        self.btn_toggle_work_float.clicked.connect(self.toggle_work_time_float)
        float_grid.addWidget(self.btn_toggle_pomo_float, 0, 0)
        float_grid.addWidget(self.btn_toggle_work_float, 0, 1)
        float_grid.setAlignment(Qt.AlignHCenter)
        v.addWidget(float_group)

        # <<< NEW: 今日行程移到最下方 >>>
        today_group = QGroupBox("📅 今日行程")
        tv = QVBoxLayout(today_group)
        self.overview_list = QListWidget()
        self.overview_list.setSelectionMode(QAbstractItemView.NoSelection)
        tv.addWidget(self.overview_list)
        v.addWidget(today_group)

        # <<< NEW: 當前任務區塊 >>>
        tasks_group = QGroupBox("📋 當前任務")
        tasks_v = QVBoxLayout(tasks_group)
        self.tasks_overview_list = QListWidget()
        self.tasks_overview_list.setSelectionMode(QAbstractItemView.NoSelection)
        tasks_v.addWidget(self.tasks_overview_list)
        v.addWidget(tasks_group)

        from PySide6.QtWidgets import QSizePolicy
        for gb in (display_group, today_group, float_group, tasks_group):
            gb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            if gb.layout(): gb.layout().setContentsMargins(16, 16, 16, 16)

        # 讓今日行程和任務列表佔據剩餘空間
        today_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        tasks_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        for btn in (self.btn_show_clock, self.btn_show_cal, self.btn_show_stats, self.btn_toggle_pomo_float, self.btn_toggle_work_float):
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumHeight(44)
        v.addStretch()
        self.tabs.addTab(page, "總覽")
        self.overview_page = page
        self.update_work_status_label()
        self.refresh_tasks() 

    def refresh_overview_events(self):
        # 重讀檔案，確保這裡是最新資料
        self.events = self.data_manager.load_events()
        self.overview_list.clear()
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        today_events = [
            e for e in self.events 
            if e.date == today_str and not e.completed
        ]
        today_events.sort(key=lambda x: x.time)
        
        if not today_events:
            item = QListWidgetItem("今天暫無待辦行程")
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.NoItemFlags)
            self.overview_list.addItem(item)
        else:
            for e in today_events:
                if e.description:
                    flat_desc = e.description.replace('\n', ' ')
                    max_len = 20
                    if len(flat_desc) > max_len:
                        disp_desc = flat_desc[:max_len] + "……"
                    else:
                        disp_desc = flat_desc
                    item_text = f"{e.time} - {e.title}: {disp_desc}"
                else:
                    item_text = f"{e.time} - {e.title}"
                
                item = QListWidgetItem(item_text)
                item.setToolTip(f"標題: {e.title}\n描述: {e.description}")
                self.overview_list.addItem(item)

    def refresh_tasks(self):
        """刷新總覽頁面的任務列表"""
        tasks = self.data_manager.load_tasks()
        self.tasks_overview_list.clear()

        pending_tasks = [t for t in tasks if t.completion < 100]

        # 按交件日期排序
        pending_tasks.sort(key=lambda t: f"{t.due_date} {t.due_time}")

        if not pending_tasks:
            item = QListWidgetItem("當前無未完成任務")
            item.setTextAlignment(Qt.AlignCenter)
            item.setFlags(Qt.NoItemFlags)
            self.tasks_overview_list.addItem(item)
        else:
            for task in pending_tasks:
                item_text = f"{task.due_date} {task.due_time} | {task.title} ({task.completion}%)"

                item = QListWidgetItem(item_text)

                if task.is_overdue():
                    item.setForeground(QColor("red"))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)

                tooltip = f"專案: {task.project_name}\n標題: {task.title}\n完成度: {task.completion}%\n交件: {task.due_date} {task.due_time}"
                if task.client:
                    tooltip += f"\n客戶: {task.client}"
                if task.description:
                    tooltip += f"\n描述: {task.description}"
                item.setToolTip(tooltip)

                self.tasks_overview_list.addItem(item)

        # 確保日曆標記同步任務交件日
        if self.calendar_window:
            self.calendar_window.refresh_events()

    def show_statistics_window(self):
        if not self.stats_window or not self.stats_window.isVisible():
            self.stats_window = StatisticsWindow(self.data_manager, self)
            self.stats_window.show()
        self.stats_window.raise_()
        self.stats_window.activateWindow()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_responsive_typography()

    def _apply_responsive_typography(self):
        base = max(16, int(min(self.width(), self.height()) * 0.022))
        title_px = int(base * 1.6)
        group_px = int(base * 1.1)
        btn_px   = int(base * 1.0)
        label_px = int(base * 0.95)
        status_label_px = int(base * 1.15)
        list_px = int(base * 1.0)
        theme = self.data_manager.load_settings().theme

        def set_px(w, px, bold=False):
            f = w.font()
            f.setFamily(theme.font_family)
            f.setPixelSize(px)
            # 应用主题字体样式
            f.setBold(theme.font_bold or bold)
            f.setItalic(theme.font_italic)
            f.setUnderline(theme.font_underline)
            f.setStrikeOut(theme.font_strikeout)
            if not bold:
                f.setWeight(QFont.Weight(theme.font_weight))
            w.setFont(f)

        for w in self.findChildren(QLabel, "pageTitle"): set_px(w, title_px, True)
        for lab in self.findChildren(QLabel):
            if lab.objectName() == "pageTitle": continue
            elif lab.objectName() == "statusLabel": set_px(lab, status_label_px)
            else: set_px(lab, label_px)
        for btn in self.findChildren(QPushButton): set_px(btn, btn_px, True)
        for lw in self.findChildren(QListWidget): set_px(lw, list_px)
        form_widgets = (QLineEdit, QDateEdit, QTimeEdit, QSpinBox, QComboBox, QCheckBox)
        for widget_class in form_widgets:
            for w in self.findChildren(widget_class): set_px(w, btn_px)
        tab_bar = self.tabs.tabBar()
        tf = tab_bar.font()
        tf.setFamily(theme.font_family)
        tf.setPixelSize(group_px)
        tf.setBold(theme.font_bold)
        tf.setItalic(theme.font_italic)
        tf.setUnderline(theme.font_underline)
        tf.setStrikeOut(theme.font_strikeout)
        tf.setWeight(QFont.Weight(theme.font_weight))
        tab_bar.setFont(tf)

    def toggle_clock(self, save_state=True):
        if not self.clock_window or not self.clock_window.isVisible():
            self.clock_window = DigitalClock(self.data_manager)
            self.clock_window.show()
            self.btn_show_clock.setText("隱藏數字時鐘")
            is_visible = True
        else:
            self.clock_window.hide()
            self.btn_show_clock.setText("顯示數字時鐘")
            is_visible = False
        if save_state:
            self.settings.clock_visible = is_visible
            self.data_manager.save_settings(self.settings)

    def toggle_calendar(self, save_state=True):
        if not self.calendar_window or not self.calendar_window.isVisible():
            self.calendar_window = CalendarWidget(self.data_manager)
            self.calendar_window.show()
            self.btn_show_cal.setText("隱藏日曆")
            is_visible = True
        else:
            self.calendar_window.hide()
            self.btn_show_cal.setText("顯示日曆")
            is_visible = False
        if save_state:
            self.settings.calendar_visible = is_visible
            self.data_manager.save_settings(self.settings)
    
    def toggle_pomodoro_float(self, save_state=True):
        if not self.pomodoro_float_window or not self.pomodoro_float_window.isVisible():
            self.pomodoro_float_window = PomodoroFloatWindow(self.data_manager)
            self.pomodoro_float_window.show()
            self.btn_toggle_pomo_float.setText("隱藏番茄鐘倒數")
            is_visible = True
            self._update_pomodoro_float_display()
        else:
            self.pomodoro_float_window.hide()
            self.btn_toggle_pomo_float.setText("顯示番茄鐘倒數")
            is_visible = False
        if save_state:
            self.settings.pomodoro_float_visible = is_visible
            self.data_manager.save_settings(self.settings)
    
    def toggle_work_time_float(self, save_state=True):
        if not self.work_time_float_window or not self.work_time_float_window.isVisible():
            self.work_time_float_window = WorkTimeFloatWindow(self.data_manager)
            self.work_time_float_window.show()
            self.btn_toggle_work_float.setText("隱藏工時計時")
            is_visible = True
            self.update_work_status_label()
        else:
            self.work_time_float_window.hide()
            self.btn_toggle_work_float.setText("顯示工時計時")
            is_visible = False
        
        if save_state:
            self.settings.work_time_float_visible = is_visible
            self.data_manager.save_settings(self.settings)

    def toggle_pomodoro(self):
        if self.pomodoro_state == "idle":
            self._start_pomodoro_work()
        else:
            self._stop_pomodoro()

    def _start_pomodoro_work(self):
        self.pomodoro_state = "working"
        work_seconds = self.settings.pomodoro_work_minutes * 60
        self.pomodoro_end_time = datetime.now() + timedelta(seconds=work_seconds)
        self.pomodoro_timer.start(work_seconds * 1000)
        self.pomodoro_display_timer.start(1000)
        if hasattr(self, 'work_page'):
            self.work_page.btn_pomodoro.setText("⏹️ 停止番茄鐘")
            self.work_page.start_pomodoro_timer()  # 啟動 WorkPage 的番茄鐘計時器
        self._update_pomodoro_display()

    def _start_pomodoro_break(self):
        self.pomodoro_state = "breaking"
        break_seconds = self.settings.pomodoro_break_minutes * 60
        self.pomodoro_end_time = datetime.now() + timedelta(seconds=break_seconds)
        self.pomodoro_timer.start(break_seconds * 1000)
        if hasattr(self, 'work_page'):
            self.work_page.btn_pomodoro.setText("⏹️ 停止番茄鐘")
            # 計時器保持運行，只需要更新顯示
            self.work_page._update_pomodoro_display()
        self._update_pomodoro_display()
        if self.settings.sound_enabled:
            self.pomodoro_sound.play()
        self.show_toast("番茄鐘 🍅", f"工作結束！現在開始休息 {self.settings.pomodoro_break_minutes} 分鐘。")

    def _stop_pomodoro(self):
        self.pomodoro_state = "idle"
        self.pomodoro_timer.stop()
        self.pomodoro_display_timer.stop()
        if hasattr(self, 'work_page'):
            self.work_page.btn_pomodoro.setText("🍅 開始番茄鐘")
            self.work_page.stop_pomodoro_timer()  # 停止 WorkPage 的番茄鐘計時器
        self._update_pomodoro_float_display()

    def _update_pomodoro_timer(self):
        if self.pomodoro_state == "working":
            self._start_pomodoro_break()
        elif self.pomodoro_state == "breaking":
            if self.settings.sound_enabled:
                self.pomodoro_sound.play()
            self.show_toast("番茄鐘 🍅", "開始工作！")
            self._start_pomodoro_work()

    def _update_pomodoro_display(self):
        if not self.pomodoro_end_time: return
        remaining = self.pomodoro_end_time - datetime.now()
        if remaining.total_seconds() < 0: remaining = timedelta(seconds=0)
        minutes, seconds = divmod(int(remaining.total_seconds()), 60)
        time_str = f"{minutes:02d}:{seconds:02d}"
        self._update_pomodoro_float_display()
    
    def _update_pomodoro_float_display(self):
        if not self.pomodoro_float_window or not self.pomodoro_float_window.isVisible(): return
        if self.pomodoro_state == "idle":
            self.pomodoro_float_window.update_display("未啟動")
        elif self.pomodoro_end_time:
            remaining = self.pomodoro_end_time - datetime.now()
            if remaining.total_seconds() < 0: remaining = timedelta(seconds=0)
            minutes, seconds = divmod(int(remaining.total_seconds()), 60)
            time_str = f"{minutes:02d}:{seconds:02d}"
            if self.pomodoro_state == "working":
                self.pomodoro_float_window.update_display(f"工作中\n{time_str}")
            elif self.pomodoro_state == "breaking":
                self.pomodoro_float_window.update_display(f"休息中\n{time_str}")

    def _on_settings_saved(self):
        self.settings = self.data_manager.load_settings()
        if self.settings.water_reminder_enabled:
            self.water_timer.start(self.settings.water_reminder_interval * 60000)
        else:
            self.water_timer.stop()
        if hasattr(self, 'water_sound'): self.water_sound.setVolume(self.settings.volume)
        if hasattr(self, 'pomodoro_sound'): self.pomodoro_sound.setVolume(self.settings.volume)
        if hasattr(self, 'notification_sound'): self.notification_sound.setVolume(self.settings.volume)
        if hasattr(self, 'task_page'):
            self.task_page.max_completed_tasks = self.settings.max_completed_tasks
            self.task_page.update_task_list()

    def update_work_status_label(self):
        self.work_records = self.data_manager.load_work_records()
        today_str = datetime.now().strftime("%Y-%m-%d")
        rec = self.work_records.get(today_str)
        
        display_text = "未打卡"
        
        if rec and rec.sessions:
            last_session = rec.sessions[-1]
            total_hours = rec.calculate_total_hours()
            
            def format_seconds(seconds):
                m, s = divmod(int(seconds), 60)
                h, m = divmod(m, 60)
                return f"{h:02d}:{m:02d}:{s:02d}"

            if last_session.get('end') is None:
                start_dt = datetime.fromisoformat(last_session['start'])
                current_duration_sec = (datetime.now() - start_dt).total_seconds()
                timer_str = format_seconds(current_duration_sec)
                display_text = f"工作中\n{timer_str}"
            else:
                total_sec = total_hours * 3600
                total_str = format_seconds(total_sec)
                display_text = f"今日總計\n{total_str}"

        if self.work_time_float_window and self.work_time_float_window.isVisible():
            self.work_time_float_window.update_display(display_text)

    def check_notifications(self):
        now = datetime.now()

        # 檢查事件提醒
        current_events = self.data_manager.load_events()
        events_changed = False
        for e in current_events:
            if not e.notified and not e.completed:
                try:
                    t = datetime.strptime(f"{e.date} {e.time}", "%Y-%m-%d %H:%M")
                    if now >= t:
                        reminder_window = EventReminderWindow(e, self)
                        self.reminder_windows.append(reminder_window)
                        reminder_window.completed_signal.connect(self.mark_event_completed)
                        reminder_window.show()

                        if self.settings.sound_enabled:
                            QApplication.beep()
                        e.notified = True
                        events_changed = True
                except ValueError:
                    continue
        if events_changed:
            self.data_manager.save_events(current_events)
            self.events = current_events
            self.refresh_overview_events()

        # 檢查任務提醒
        current_tasks = self.data_manager.load_tasks()
        tasks_changed = False
        for task in current_tasks:
            # 跳過已完成的任務
            if task.completion >= 100:
                continue

            try:
                due_datetime = datetime.strptime(f"{task.due_date} {task.due_time}", "%Y-%m-%d %H:%M")

                # 檢查提前提醒
                if task.remind_before > 0 and not task.notified_before:
                    remind_time = due_datetime - timedelta(minutes=task.remind_before)
                    if now >= remind_time:
                        reminder_window = TaskReminderWindow(task, is_due=False, parent=self)
                        self.reminder_windows.append(reminder_window)
                        reminder_window.completion_changed.connect(self.update_task_completion)
                        reminder_window.show()

                        if self.settings.sound_enabled:
                            self.notification_sound.play()
                        task.notified_before = True
                        tasks_changed = True

                # 檢查到期提醒
                if not task.notified_due and now >= due_datetime:
                    reminder_window = TaskReminderWindow(task, is_due=True, parent=self)
                    self.reminder_windows.append(reminder_window)
                    reminder_window.completion_changed.connect(self.update_task_completion)
                    reminder_window.show()

                    if self.settings.sound_enabled:
                        self.notification_sound.play()
                    task.notified_due = True
                    tasks_changed = True

            except ValueError:
                continue

        if tasks_changed:
            self.data_manager.save_tasks(current_tasks)
            if hasattr(self, 'task_page'):
                self.task_page.tasks = current_tasks
                self.task_page.update_task_list()
            self.refresh_tasks()

    def update_task_completion(self, task_id, new_completion):
        """更新任務完成度（從提醒視窗調用）"""
        current_tasks = self.data_manager.load_tasks()
        for task in current_tasks:
            if task.id == task_id:
                task.completion = new_completion
                break
        self.data_manager.save_tasks(current_tasks)

        # 更新任務頁面
        if hasattr(self, 'task_page'):
            self.task_page.tasks = current_tasks
            self.task_page.update_task_list()

        # 更新總覽頁面
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
        
        if hasattr(self, 'event_page'):
            self.event_page.events = current_events
            self.event_page.update_event_list()
        if hasattr(self, 'past_events_page'):
            self.past_events_page.refresh_list()

    def water_reminder(self):
        if self.settings.water_reminder_enabled:
            if self.settings.sound_enabled:
                self.water_sound.play()
            self.show_toast("喝水提醒 💧", "該喝水囉！休息一下，保持身體水分～")

class EventEditDialog(QDialog):
    """事件編輯對話框"""
    def __init__(self, data_manager, event_data=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.event_data = event_data
        self.setWindowTitle("編輯行程" if event_data else "新增行程")
        self.setMinimumSize(500, 400)
        self._build_ui()
        if self.event_data:
            self._load_event_data()
        self.data_manager.restore_window_geometry("event_edit_dialog", self)
        if self.width() < 500 or self.height() < 400:
            self.resize(600, 450)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 標題
        title_row = QWidget()
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.addWidget(QLabel("標題:"))
        self.title_input = QLineEdit()
        title_layout.addWidget(self.title_input, 1)
        layout.addWidget(title_row)

        # 日期時間
        datetime_row = QWidget()
        dt_layout = QHBoxLayout(datetime_row)
        dt_layout.setContentsMargins(0, 0, 0, 0)
        dt_layout.addWidget(QLabel("日期:"))
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        dt_layout.addWidget(self.date_input, 1)
        dt_layout.addSpacing(10)
        dt_layout.addWidget(QLabel("時間:"))
        self.time_input = QTimeEdit(QTime.currentTime())
        dt_layout.addWidget(self.time_input, 1)
        layout.addWidget(datetime_row)

        # 描述
        desc_label = QLabel("描述:")
        layout.addWidget(desc_label)
        self.desc_input = QTextEdit()
        self.desc_input.setMaximumHeight(120)
        self.desc_input.setPlaceholderText("可輸入詳細描述（支援分行）...")
        self.desc_input.setTabChangesFocus(True)
        layout.addWidget(self.desc_input)

        # 狀態
        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.addWidget(QLabel("狀態:"))
        self.completed_checkbox = QCheckBox("已完成")
        status_layout.addWidget(self.completed_checkbox)
        status_layout.addStretch()
        layout.addWidget(status_row)

        layout.addStretch()

        # 按鈕
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        save_btn = QPushButton("儲存")
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self._on_save_clicked)
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def _load_event_data(self):
        """載入事件資料到表單"""
        self.title_input.setText(self.event_data.title)
        self.date_input.setDate(QDate.fromString(self.event_data.date, "yyyy-MM-dd"))
        self.time_input.setTime(QTime.fromString(self.event_data.time, "HH:mm"))
        self.desc_input.setText(self.event_data.description)
        self.completed_checkbox.setChecked(self.event_data.completed)

    def _on_save_clicked(self):
        """儲存按鈕點擊事件"""
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "警告", "請輸入行程標題！")
            return

        if self.event_data:
            # 編輯現有事件
            new_date = self.date_input.date().toString("yyyy-MM-dd")
            new_time = self.time_input.time().toString("HH:mm")

            event_dt = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M")
            if datetime.now() > event_dt:
                self.event_data.notified = True
            elif self.event_data.notified:
                self.event_data.notified = False

            self.event_data.title = self.title_input.text().strip()
            self.event_data.date = new_date
            self.event_data.time = new_time
            self.event_data.description = self.desc_input.toPlainText().strip()
            self.event_data.completed = self.completed_checkbox.isChecked()
        else:
            # 新增事件
            import uuid
            date_str = self.date_input.date().toString("yyyy-MM-dd")
            time_str = self.time_input.time().toString("HH:mm")
            event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            is_past = datetime.now() > event_dt

            self.event_data = Event(
                id=uuid.uuid4().hex,
                title=self.title_input.text().strip(),
                date=date_str,
                time=time_str,
                description=self.desc_input.toPlainText().strip(),
                completed=self.completed_checkbox.isChecked(),
                notified=is_past
            )

        self.accept()

    def get_event(self):
        """獲取編輯後的事件"""
        return self.event_data

    def closeEvent(self, event):
        self.data_manager.save_window_geometry("event_edit_dialog", self)
        super().closeEvent(event)

class WorkSessionEditDialog(QDialog):
    """工時記錄編輯對話框"""
    def __init__(self, data_manager, date_str, sessions=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.date_str = date_str
        self.sessions = sessions if sessions else []
        self.setWindowTitle(f"編輯工時 - {date_str}")
        self.setMinimumSize(600, 400)
        self._build_ui()
        self._load_sessions()
        self.data_manager.restore_window_geometry("work_session_edit_dialog", self)
        if self.width() < 600 or self.height() < 400:
            self.resize(700, 500)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 標題
        title_label = QLabel(f"📅 日期: {self.date_str}")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title_label)

        # 工時列表
        list_label = QLabel("工時記錄:")
        layout.addWidget(list_label)

        self.sessions_tree = QTreeWidget()
        self.sessions_tree.setHeaderLabels(["開始時間", "結束時間", "時長(小時)"])
        self.sessions_tree.setColumnWidth(0, 200)
        self.sessions_tree.setColumnWidth(1, 200)
        layout.addWidget(self.sessions_tree)

        # 按鈕
        button_layout = QHBoxLayout()
        add_btn = QPushButton("新增記錄")
        add_btn.clicked.connect(self._add_session)
        edit_btn = QPushButton("編輯選中")
        edit_btn.clicked.connect(self._edit_session)
        delete_btn = QPushButton("刪除選中")
        delete_btn.clicked.connect(self._delete_session)
        button_layout.addWidget(add_btn)
        button_layout.addWidget(edit_btn)
        button_layout.addWidget(delete_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        layout.addStretch()

        # 關閉按鈕
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        save_btn = QPushButton("儲存")
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self._on_save_clicked)
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        close_layout.addWidget(save_btn)
        close_layout.addWidget(cancel_btn)
        layout.addLayout(close_layout)

    def _load_sessions(self):
        """載入工時記錄到列表"""
        self.sessions_tree.clear()
        for session in self.sessions:
            start = session.get('start', '')
            end = session.get('end', '')
            duration = ""
            if start and end:
                try:
                    sd = datetime.fromisoformat(start)
                    ed = datetime.fromisoformat(end)
                    duration_hours = (ed - sd).total_seconds() / 3600
                    duration = f"{duration_hours:.2f}"
                    start_display = sd.strftime("%Y-%m-%d %H:%M:%S")
                    end_display = ed.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    start_display = start
                    end_display = end
            else:
                start_display = start
                end_display = end if end else "進行中"

            item = QTreeWidgetItem([start_display, end_display, duration])
            item.setData(0, Qt.UserRole, session)
            self.sessions_tree.addTopLevelItem(item)

    def _add_session(self):
        """新增工時記錄"""
        dialog = SingleSessionEditDialog(self.date_str, parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_session = dialog.get_session()
            self.sessions.append(new_session)
            self._load_sessions()

    def _edit_session(self):
        """編輯選中的工時記錄"""
        selected_items = self.sessions_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "請選擇要編輯的記錄")
            return

        item = selected_items[0]
        session = item.data(0, Qt.UserRole)
        index = self.sessions.index(session)

        dialog = SingleSessionEditDialog(self.date_str, session, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.sessions[index] = dialog.get_session()
            self._load_sessions()

    def _delete_session(self):
        """刪除選中的工時記錄"""
        selected_items = self.sessions_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "請選擇要刪除的記錄")
            return

        reply = QMessageBox.question(
            self, "確認刪除",
            "確定要刪除選中的工時記錄嗎？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            item = selected_items[0]
            session = item.data(0, Qt.UserRole)
            self.sessions.remove(session)
            self._load_sessions()

    def _on_save_clicked(self):
        """儲存按鈕點擊事件"""
        self.accept()

    def get_sessions(self):
        """獲取編輯後的工時記錄"""
        return self.sessions

    def closeEvent(self, event):
        self.data_manager.save_window_geometry("work_session_edit_dialog", self)
        super().closeEvent(event)

class SingleSessionEditDialog(QDialog):
    """單個工時記錄編輯對話框"""
    def __init__(self, date_str, session=None, parent=None):
        super().__init__(parent)
        self.date_str = date_str
        self.session = session
        self.setWindowTitle("編輯工時記錄" if session else "新增工時記錄")
        self.setMinimumSize(400, 200)
        self._build_ui()
        if self.session:
            self._load_session_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 開始時間
        start_row = QWidget()
        start_layout = QHBoxLayout(start_row)
        start_layout.setContentsMargins(0, 0, 0, 0)
        start_layout.addWidget(QLabel("開始時間:"))
        self.start_datetime = QDateTimeEdit(QDateTime.currentDateTime())
        self.start_datetime.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_datetime.setCalendarPopup(True)
        start_layout.addWidget(self.start_datetime, 1)
        layout.addWidget(start_row)

        # 結束時間
        end_row = QWidget()
        end_layout = QHBoxLayout(end_row)
        end_layout.setContentsMargins(0, 0, 0, 0)
        end_layout.addWidget(QLabel("結束時間:"))
        self.end_datetime = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_datetime.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_datetime.setCalendarPopup(True)
        end_layout.addWidget(self.end_datetime, 1)
        layout.addWidget(end_row)

        layout.addStretch()

        # 按鈕
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        save_btn = QPushButton("儲存")
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self._on_save_clicked)
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def _load_session_data(self):
        """載入工時記錄到表單"""
        start = self.session.get('start', '')
        end = self.session.get('end', '')

        if start:
            try:
                start_dt = datetime.fromisoformat(start)
                self.start_datetime.setDateTime(QDateTime(
                    QDate(start_dt.year, start_dt.month, start_dt.day),
                    QTime(start_dt.hour, start_dt.minute, start_dt.second)
                ))
            except Exception:
                pass

        if end:
            try:
                end_dt = datetime.fromisoformat(end)
                self.end_datetime.setDateTime(QDateTime(
                    QDate(end_dt.year, end_dt.month, end_dt.day),
                    QTime(end_dt.hour, end_dt.minute, end_dt.second)
                ))
            except Exception:
                pass

    def _on_save_clicked(self):
        """儲存按鈕點擊事件"""
        start_qdt = self.start_datetime.dateTime()
        end_qdt = self.end_datetime.dateTime()

        if start_qdt >= end_qdt:
            QMessageBox.warning(self, "警告", "結束時間必須晚於開始時間！")
            return

        self.accept()

    def get_session(self):
        """獲取編輯後的工時記錄"""
        start_qdt = self.start_datetime.dateTime()
        end_qdt = self.end_datetime.dateTime()

        start_dt = datetime(
            start_qdt.date().year(),
            start_qdt.date().month(),
            start_qdt.date().day(),
            start_qdt.time().hour(),
            start_qdt.time().minute(),
            start_qdt.time().second()
        )

        end_dt = datetime(
            end_qdt.date().year(),
            end_qdt.date().month(),
            end_qdt.date().day(),
            end_qdt.time().hour(),
            end_qdt.time().minute(),
            end_qdt.time().second()
        )

        return {
            'start': start_dt.isoformat(),
            'end': end_dt.isoformat()
        }

class TaskEditDialog(QDialog):
    """任務編輯對話框"""
    def __init__(self, data_manager, task=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.task = task
        self.price_items_widgets = []
        self.setWindowTitle("編輯任務" if task else "新增任務")
        self.setMinimumSize(700, 600)
        self._build_ui()
        if self.task:
            self._load_task_data()
        # 恢復上次儲存的視窗尺寸
        self.data_manager.restore_window_geometry("task_edit_dialog", self)
        # 如果沒有儲存的尺寸，使用預設值
        if self.width() < 700 or self.height() < 600:
            self.resize(800, 700)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(15)
        row1 = QWidget()
        row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.addWidget(QLabel("專案:"))
        self.project_input = QLineEdit()
        row1_layout.addWidget(self.project_input, 1)
        row1_layout.addSpacing(15)
        row1_layout.addWidget(QLabel("標題:"))
        self.title_input = QLineEdit()
        row1_layout.addWidget(self.title_input, 1)
        content_layout.addWidget(row1)
        row2 = QWidget()
        row2_layout = QHBoxLayout(row2)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.addWidget(QLabel("交件日期:"))
        self.due_date_input = QDateEdit(QDate.currentDate())
        self.due_date_input.setCalendarPopup(True)
        row2_layout.addWidget(self.due_date_input, 1)
        row2_layout.addSpacing(15)
        row2_layout.addWidget(QLabel("交件時間:"))
        self.due_time_input = QTimeEdit(QTime(23, 59))
        row2_layout.addWidget(self.due_time_input, 1)
        content_layout.addWidget(row2)
        row3 = QWidget()
        row3_layout = QHBoxLayout(row3)
        row3_layout.setContentsMargins(0, 0, 0, 0)
        self.remind_checkbox = QCheckBox("提前提醒")
        row3_layout.addWidget(self.remind_checkbox)
        self.remind_minutes_input = QSpinBox()
        self.remind_minutes_input.setMinimum(1)
        self.remind_minutes_input.setMaximum(10080)
        self.remind_minutes_input.setValue(30)
        self.remind_minutes_input.setSuffix(" 分鐘")
        row3_layout.addWidget(self.remind_minutes_input)
        row3_layout.addStretch()
        content_layout.addWidget(row3)
        price_group = QGroupBox("價格項目")
        price_main_layout = QVBoxLayout(price_group)

        # 添加表頭標籤
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 0, 5, 0)
        header_layout.setSpacing(8)

        name_header = QLabel("項目名稱")
        name_header.setStyleSheet("font-weight: bold; color: #666;")
        header_layout.addWidget(name_header, 2)

        price_header = QLabel("單價")
        price_header.setStyleSheet("font-weight: bold; color: #666;")
        header_layout.addWidget(price_header, 1)

        qty_header = QLabel("數量")
        qty_header.setStyleSheet("font-weight: bold; color: #666;")
        header_layout.addWidget(qty_header, 1)

        # 占位符，對應刪除按鈕的位置
        spacer_label = QLabel("")
        spacer_label.setMaximumWidth(60)
        header_layout.addWidget(spacer_label)

        price_main_layout.addWidget(header_widget)

        price_scroll = QScrollArea()
        price_scroll.setWidgetResizable(True)
        price_scroll.setMinimumHeight(150)
        price_scroll.setMaximumHeight(250)
        price_scroll.setFrameShape(QFrame.StyledPanel)
        self.price_items_container = QWidget()
        self.price_items_layout = QVBoxLayout(self.price_items_container)
        self.price_items_layout.setContentsMargins(5, 5, 5, 5)
        self.price_items_layout.setSpacing(8)
        self.price_items_layout.addStretch()
        price_scroll.setWidget(self.price_items_container)
        price_main_layout.addWidget(price_scroll)
        price_btn_row = QWidget()
        price_btn_layout = QHBoxLayout(price_btn_row)
        price_btn_layout.setContentsMargins(0, 0, 0, 0)
        add_price_btn = QPushButton("+ 新增項目")
        add_price_btn.clicked.connect(self._add_price_item_widget)
        price_btn_layout.addWidget(add_price_btn)
        self.total_price_label = QLabel("總價: $0.00")
        self.total_price_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        price_btn_layout.addStretch()
        price_btn_layout.addWidget(self.total_price_label)
        price_main_layout.addWidget(price_btn_row)
        content_layout.addWidget(price_group)
        row5 = QWidget()
        row5_layout = QHBoxLayout(row5)
        row5_layout.setContentsMargins(0, 0, 0, 0)
        row5_layout.addWidget(QLabel("客戶:"))
        self.client_input = QLineEdit()
        row5_layout.addWidget(self.client_input, 1)
        row5_layout.addSpacing(15)
        row5_layout.addWidget(QLabel("幣別:"))
        self.currency_input = QLineEdit()
        self.currency_input.setPlaceholderText("例: NTD, USD, EUR...")
        self.currency_input.setMaximumWidth(150)
        row5_layout.addWidget(self.currency_input)
        content_layout.addWidget(row5)
        desc_row = QWidget()
        desc_layout = QVBoxLayout(desc_row)
        desc_layout.setContentsMargins(0, 0, 0, 0)
        desc_layout.addWidget(QLabel("描述:"))
        self.desc_input = QTextEdit()
        self.desc_input.setMaximumHeight(80)
        self.desc_input.setPlaceholderText("可輸入詳細描述（支援分行）...")
        self.desc_input.setTabChangesFocus(True)
        desc_layout.addWidget(self.desc_input)
        content_layout.addWidget(desc_row)
        row7 = QWidget()
        row7_layout = QHBoxLayout(row7)
        row7_layout.setContentsMargins(0, 0, 0, 0)
        row7_layout.addWidget(QLabel("完成度:"))
        self.completion_slider = QSlider(Qt.Horizontal)
        self.completion_slider.setMinimum(0)
        self.completion_slider.setMaximum(100)
        self.completion_slider.setValue(0)
        self.completion_slider.setTickPosition(QSlider.TicksBelow)
        self.completion_slider.setTickInterval(10)
        self.completion_slider.valueChanged.connect(self._update_completion_label)
        row7_layout.addWidget(self.completion_slider, 1)
        self.completion_label = QLabel("0%")
        self.completion_label.setMinimumWidth(50)
        row7_layout.addWidget(self.completion_label)
        content_layout.addWidget(row7)
        scroll.setWidget(content_widget)
        layout.addWidget(scroll)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        save_btn = QPushButton("儲存")
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self._on_save_clicked)
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        # 只在新增任務時添加默認價格項目
        if not self.task:
            self._add_price_item_widget()

    def _toggle_remind(self, state):
        self.remind_minutes_input.setEnabled(self.remind_checkbox.isChecked())

    def _update_completion_label(self, value):
        self.completion_label.setText(f"{value}%")

    def _add_price_item_widget(self):
        if self.price_items_layout.count() > 0:
            last_item = self.price_items_layout.itemAt(self.price_items_layout.count() - 1)
            if last_item.spacerItem():
                self.price_items_layout.removeItem(last_item)
        item_widget = QWidget()
        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(8)
        name_input = QLineEdit()
        name_input.setPlaceholderText("項目名稱")
        item_layout.addWidget(name_input, 2)
        unit_price_input = QDoubleSpinBox()
        unit_price_input.setPrefix("$")
        unit_price_input.setMinimum(0)
        unit_price_input.setMaximum(999999)
        unit_price_input.setDecimals(2)
        unit_price_input.valueChanged.connect(self._calculate_total)
        item_layout.addWidget(unit_price_input, 1)
        quantity_input = QDoubleSpinBox()
        quantity_input.setPrefix("x")
        quantity_input.setMinimum(0.01)
        quantity_input.setMaximum(99999)
        quantity_input.setDecimals(2)
        quantity_input.setValue(1.0)
        quantity_input.valueChanged.connect(self._calculate_total)
        item_layout.addWidget(quantity_input, 1)
        remove_btn = QPushButton("刪除")
        remove_btn.setMaximumWidth(60)
        remove_btn.setStyleSheet("QPushButton { background-color: #ff4444; color: white; font-weight: bold; }")
        remove_btn.setToolTip("刪除此項目")
        remove_btn.clicked.connect(lambda: self._remove_price_item_widget(item_widget))
        item_layout.addWidget(remove_btn)
        self.price_items_layout.addWidget(item_widget)
        self.price_items_widgets.append({'widget': item_widget, 'name': name_input, 'unit_price': unit_price_input, 'quantity': quantity_input})
        self.price_items_layout.addStretch()

    def _remove_price_item_widget(self, widget):
        for i, item in enumerate(self.price_items_widgets):
            if item['widget'] == widget:
                self.price_items_widgets.pop(i)
                widget.deleteLater()
                break
        self._calculate_total()

    def _calculate_total(self):
        total = 0.0
        for item in self.price_items_widgets:
            total += item['unit_price'].value() * item['quantity'].value()
        self.total_price_label.setText(f"總價: ${total:,.2f}")

    def _save_geometry(self):
        """Persist dialog geometry so size/position are restored next time."""
        self.data_manager.save_window_geometry("task_edit_dialog", self)

    def _validate_required_fields(self) -> bool:
        project = self.project_input.text().strip()
        title = self.title_input.text().strip()

        if not project:
            QMessageBox.warning(self, "提示", "請輸入專案名稱！")
            self.project_input.setFocus()
            return False

        if not title:
            QMessageBox.warning(self, "提示", "請輸入任務標題！")
            self.title_input.setFocus()
            return False

        return True

    def _load_task_data(self):
        if not self.task:
            return
        self.project_input.setText(self.task.project_name)
        self.title_input.setText(self.task.title)
        self.due_date_input.setDate(QDate.fromString(self.task.due_date, "yyyy-MM-dd"))
        self.due_time_input.setTime(QTime.fromString(self.task.due_time, "HH:mm"))
        self.client_input.setText(self.task.client)
        self.currency_input.setText(getattr(self.task, 'currency', 'NTD'))  # 載入幣別，預設為NTD
        self.desc_input.setPlainText(self.task.description)
        self.completion_slider.setValue(self.task.completion)
        if self.task.remind_before > 0:
            self.remind_checkbox.setChecked(True)
            self.remind_minutes_input.setValue(self.task.remind_before)
        for item_data in self.price_items_widgets:
            item_data['widget'].deleteLater()
        self.price_items_widgets.clear()
        if self.task.price_items:
            for price_item in self.task.price_items:
                self._add_price_item_widget()
                item = self.price_items_widgets[-1]
                item['name'].setText(price_item.get('name', ''))
                item['unit_price'].setValue(price_item.get('unit_price', 0))
                item['quantity'].setValue(price_item.get('quantity', 1))
        else:
            self._add_price_item_widget()
        self._calculate_total()

    def _on_save_clicked(self):
        """儲存按鈕點擊事件"""
        self.accept()

    def accept(self):
        if not self._validate_required_fields():
            return
        self._save_geometry()
        super().accept()

    def reject(self):
        self._save_geometry()
        super().reject()

    def get_task_data(self):
        project = self.project_input.text().strip()
        title = self.title_input.text().strip()
        if not project or not title:
            return None
        price_items = []
        for item in self.price_items_widgets:
            name = item['name'].text().strip()
            if name:
                price_items.append({'name': name, 'unit_price': item['unit_price'].value(), 'quantity': item['quantity'].value()})
        currency = self.currency_input.text().strip() or 'NTD'  # 取得幣別，預設為NTD
        return {'project_name': project, 'title': title, 'due_date': self.due_date_input.date().toString("yyyy-MM-dd"), 'due_time': self.due_time_input.time().toString("HH:mm"), 'client': self.client_input.text().strip(), 'currency': currency, 'description': self.desc_input.toPlainText(), 'completion': self.completion_slider.value(), 'price_items': price_items, 'remind_before': self.remind_minutes_input.value() if self.remind_checkbox.isChecked() else 0}

    def closeEvent(self, event):
        """關閉時儲存視窗尺寸"""
        self._save_geometry()
        super().closeEvent(event)

class TaskPage(QWidget):
    """工作任務管理頁面"""
    def __init__(self, data_manager, main_window=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.main_window = main_window
        self.tasks = self.data_manager.load_tasks()
        self.max_completed_tasks = self.data_manager.load_settings().max_completed_tasks
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignTop)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        title = QLabel("📋 工作任務管理")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        # 新增任务按钮和搜尋欄
        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)

        add_btn = QPushButton("➕ 新增任務")
        add_btn.setMinimumHeight(40)
        add_btn.clicked.connect(self.open_add_task_dialog)
        button_layout.addWidget(add_btn, 2)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜尋任務（標題、專案名稱、客戶）...")
        self.search_input.setMinimumHeight(40)
        self.search_input.textChanged.connect(self.update_task_list)
        button_layout.addWidget(self.search_input, 3)

        root.addWidget(button_row)

        # 現有任務列表區
        list_card = QGroupBox("現有任務 (雙擊以編輯)")
        list_layout = QVBoxLayout(list_card)
        self.task_table = QTableWidget()
        self.task_table.setColumnCount(5)
        self.task_table.setHorizontalHeaderLabels(["創建日期", "交件時間", "完成度", "專案名稱", "標題"])
        self.task_table.horizontalHeader().setStretchLastSection(True)
        self.task_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.task_table.setSelectionMode(QTableWidget.SingleSelection)
        self.task_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.task_table.cellDoubleClicked.connect(self.open_edit_task_dialog_from_table)
        delete_btn = QPushButton("刪除選中任務")
        delete_btn.clicked.connect(self.delete_task)
        list_layout.addWidget(self.task_table)
        list_layout.addWidget(delete_btn)
        root.addWidget(list_card, 3)

        # 過去任務列表區
        completed_card = QGroupBox("過去任務 (雙擊以編輯)")
        completed_layout = QVBoxLayout(completed_card)
        self.completed_task_table = QTableWidget()
        self.completed_task_table.setColumnCount(5)
        self.completed_task_table.setHorizontalHeaderLabels(["創建日期", "交件時間", "完成度", "專案名稱", "標題"])
        self.completed_task_table.horizontalHeader().setStretchLastSection(True)
        self.completed_task_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.completed_task_table.setSelectionMode(QTableWidget.SingleSelection)
        self.completed_task_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.completed_task_table.cellDoubleClicked.connect(self.open_edit_completed_task_dialog_from_table)
        delete_completed_btn = QPushButton("刪除選中已完成任務")
        delete_completed_btn.clicked.connect(self.delete_completed_task)
        completed_layout.addWidget(self.completed_task_table)
        completed_layout.addWidget(delete_completed_btn)
        root.addWidget(completed_card, 2)

        self.update_task_list()

    def open_add_task_dialog(self):
        """開啟新增任務視窗"""
        dialog = TaskEditDialog(self.data_manager, parent=self)
        if dialog.exec() == QDialog.Accepted:
            task_data = dialog.get_task_data()

            now = datetime.now()
            new_task = TaskItem(
                id=str(int(now.timestamp() * 1000)),
                project_name=task_data['project_name'],
                title=task_data['title'],
                due_date=task_data['due_date'],
                due_time=task_data['due_time'],
                client=task_data['client'],
                currency=task_data['currency'],
                description=task_data['description'],
                completion=task_data['completion'],
                price_items=task_data['price_items'],
                remind_before=task_data['remind_before'],
                created_date=now.strftime("%Y-%m-%d"),
                created_time=now.strftime("%H:%M")
            )
            self.tasks.append(new_task)
            self.data_manager.save_tasks(self.tasks)
            self.update_task_list()

            if self.main_window and hasattr(self.main_window, 'refresh_tasks'):
                self.main_window.refresh_tasks()

    def open_edit_task_dialog_from_table(self, row, column):
        """從現有任務表格打開編輯任務對話框"""
        task_id = self.task_table.item(row, 0).data(Qt.UserRole)
        task = self._find_task_by_id(task_id)
        if not task:
            return

        dialog = TaskEditDialog(self.data_manager, task=task, parent=self)
        if dialog.exec() == QDialog.Accepted:
            task_data = dialog.get_task_data()
            self._update_task(task, task_data)

    def open_edit_completed_task_dialog_from_table(self, row, column):
        """從過去任務表格打開編輯任務對話框"""
        task_id = self.completed_task_table.item(row, 0).data(Qt.UserRole)
        task = self._find_task_by_id(task_id)
        if not task:
            return

        dialog = TaskEditDialog(self.data_manager, task=task, parent=self)
        if dialog.exec() == QDialog.Accepted:
            task_data = dialog.get_task_data()
            self._update_task(task, task_data)

    def _find_task_by_id(self, task_id):
        """通過ID查找任務"""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def _update_task(self, task, task_data):
        """更新任務數據"""
        task.project_name = task_data['project_name']
        task.title = task_data['title']
        task.due_date = task_data['due_date']
        task.due_time = task_data['due_time']
        task.client = task_data['client']
        task.currency = task_data['currency']
        task.description = task_data['description']
        task.completion = task_data['completion']
        task.price_items = task_data['price_items']
        task.remind_before = task_data['remind_before']

        self.data_manager.save_tasks(self.tasks)
        self.update_task_list()

        # 通知主窗口更新總覽
        if self.main_window and hasattr(self.main_window, 'refresh_tasks'):
            self.main_window.refresh_tasks()

        # 通知統計視窗更新
        if self.main_window and hasattr(self.main_window, 'stats_window'):
            if self.main_window.stats_window and self.main_window.stats_window.isVisible():
                self.main_window.stats_window.refresh_data()

    def delete_task(self):
        """删除选中的現有任务"""
        current_row = self.task_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "請先選擇要刪除的任務！")
            return

        task_id = self.task_table.item(current_row, 0).data(Qt.UserRole)
        task = self._find_task_by_id(task_id)
        if not task:
            return

        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要刪除任務「{task.title}」嗎？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.tasks.remove(task)
            self.data_manager.save_tasks(self.tasks)
            self.update_task_list()

            if self.main_window and hasattr(self.main_window, 'refresh_tasks'):
                self.main_window.refresh_tasks()

    def delete_completed_task(self):
        """刪除選中的已完成任務"""
        current_row = self.completed_task_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "提示", "請先選擇要刪除的任務！")
            return

        task_id = self.completed_task_table.item(current_row, 0).data(Qt.UserRole)
        task = self._find_task_by_id(task_id)
        if not task:
            return

        reply = QMessageBox.question(
            self, "確認刪除",
            f"確定要刪除任務「{task.title}」嗎？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.tasks.remove(task)
            self.data_manager.save_tasks(self.tasks)
            self.update_task_list()

            if self.main_window and hasattr(self.main_window, 'refresh_tasks'):
                self.main_window.refresh_tasks()

    def update_task_list(self):
        """更新任务列表"""
        search_text = self.search_input.text().lower() if hasattr(self, 'search_input') else ""

        # 分離進行中和已完成的任務
        active_tasks = []
        completed_tasks = []

        for task in self.tasks:
            # 搜尋過濾（標題、專案名稱、客戶）
            if search_text:
                if search_text not in task.title.lower() and search_text not in task.project_name.lower() and search_text not in task.client.lower():
                    continue

            if task.completion >= 100:
                completed_tasks.append(task)
            else:
                active_tasks.append(task)

        # 更新現有任務表格
        self.task_table.setRowCount(0)
        for row_idx, task in enumerate(active_tasks):
            self._add_task_to_table(self.task_table, row_idx, task)

        # 更新過去任務表格（依設定的顯示筆數）
        self.completed_task_table.setRowCount(0)
        # 按創建日期排序，最新的在前
        completed_tasks.sort(key=lambda t: f"{t.created_date} {t.created_time}", reverse=True)
        max_completed = getattr(self, "max_completed_tasks", self.data_manager.load_settings().max_completed_tasks)
        for row_idx, task in enumerate(completed_tasks[:max_completed]):
            self._add_task_to_table(self.completed_task_table, row_idx, task)

    def _add_task_to_table(self, table, row_idx, task):
        """添加任務到指定表格"""
        table.insertRow(row_idx)

        # 創建日期 (省略年份)
        created_date_parts = task.created_date.split('-')
        created_display = f"{created_date_parts[1]}/{created_date_parts[2]} {task.created_time}" if len(created_date_parts) == 3 else f"{task.created_date} {task.created_time}"
        created_item = QTableWidgetItem(created_display)
        created_item.setData(Qt.UserRole, task.id)  # 存儲任務ID

        # 交件時間 (省略年份)
        due_date_parts = task.due_date.split('-')
        due_display = f"{due_date_parts[1]}/{due_date_parts[2]} {task.due_time}" if len(due_date_parts) == 3 else f"{task.due_date} {task.due_time}"
        due_item = QTableWidgetItem(due_display)

        # 完成度
        completion_item = QTableWidgetItem(f"{task.completion}%")
        completion_item.setTextAlignment(Qt.AlignCenter)

        # 專案名稱
        project_item = QTableWidgetItem(task.project_name)

        # 標題
        title_item = QTableWidgetItem(task.title)

        # 如果超期且未完成，顯示為紅色粗體
        if task.is_overdue():
            for item in [created_item, due_item, completion_item, project_item, title_item]:
                item.setForeground(QColor("red"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)

        table.setItem(row_idx, 0, created_item)
        table.setItem(row_idx, 1, due_item)
        table.setItem(row_idx, 2, completion_item)
        table.setItem(row_idx, 3, project_item)
        table.setItem(row_idx, 4, title_item)

class EventPage(QWidget):
    def __init__(self, data_manager, calendar_window_getter=None, main_window=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.calendar_window_getter = calendar_window_getter
        self.main_window = main_window 
        self.events = self.data_manager.load_events()
        self.editing_event_id = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignTop)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)
        title = QLabel("📅 行程管理")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        card = QGroupBox("新增/編輯行程")
        # <<< CHANGE: 改用 QVBoxLayout，讓我們可以自由控制每一行的長相 >>>
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10) # 設定行距，讓畫面不要太擠
        
        # 1. 標題列 [標籤: 標題] [輸入框]
        title_box = QWidget()
        t_layout = QHBoxLayout(title_box)
        t_layout.setContentsMargins(0, 0, 0, 0)
        t_layout.addWidget(QLabel("標題:"))
        self.title_input = QLineEdit()
        t_layout.addWidget(self.title_input)
        card_layout.addWidget(title_box)

        # 2. 日期時間列 [標籤: 日期] [日期框] [標籤: 時間] [時間框]
        dt_box = QWidget()
        dt_layout = QHBoxLayout(dt_box)
        dt_layout.setContentsMargins(0, 0, 0, 0)
        self.date_input = QDateEdit(QDate.currentDate()); self.date_input.setCalendarPopup(True)
        self.time_input = QTimeEdit(QTime.currentTime())
        
        dt_layout.addWidget(QLabel("日期:"))
        dt_layout.addWidget(self.date_input, 1)
        dt_layout.addSpacing(10)
        dt_layout.addWidget(QLabel("時間:"))
        dt_layout.addWidget(self.time_input, 1)
        card_layout.addWidget(dt_box)
        
        # 3. 描述列 [標籤: 描述] [多行輸入框]
        desc_box = QWidget()
        d_layout = QHBoxLayout(desc_box)
        d_layout.setContentsMargins(0, 0, 0, 0)
        
        desc_label = QLabel("描述:")
        desc_label.setAlignment(Qt.AlignTop) # 讓標籤靠上對齊，不要跑道中間
        d_layout.addWidget(desc_label)
        
        self.desc_input = QTextEdit()
        self.desc_input.setMaximumHeight(60) 
        self.desc_input.setPlaceholderText("可輸入詳細描述（支援分行）...")
        self.desc_input.setTabChangesFocus(True)
        d_layout.addWidget(self.desc_input)
        card_layout.addWidget(desc_box)
        
        # 4. 狀態列 [標籤: 狀態] [勾選框]
        status_box = QWidget()
        s_layout = QHBoxLayout(status_box)
        s_layout.setContentsMargins(0, 0, 0, 0)
        s_layout.addWidget(QLabel("狀態:"))
        self.completed_checkbox = QCheckBox("已完成")
        s_layout.addWidget(self.completed_checkbox)
        s_layout.addStretch() # 加上彈簧，讓勾選框靠左
        card_layout.addWidget(status_box)
        
        # 5. 按鈕區
        self.add_btn = QPushButton("新增")
        self.add_btn.clicked.connect(self.add_or_save_event)
        self.cancel_btn = QPushButton("取消編輯")
        self.cancel_btn.clicked.connect(self.cancel_edit)
        self.cancel_btn.hide()
        
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.cancel_btn)
        card_layout.addLayout(button_layout) # 直接加入 card_layout
        
        root.addWidget(card)

        # 列表區 (維持原樣)
        list_card = QGroupBox("現有行程 (雙擊以編輯)")
        v = QVBoxLayout(list_card)
        self.event_list = QListWidget()
        self.event_list.itemDoubleClicked.connect(self.start_editing_event)
        self.update_event_list()
        delete_btn = QPushButton("刪除選中行程")
        delete_btn.clicked.connect(self.delete_event)
        v.addWidget(self.event_list)
        v.addWidget(delete_btn)
        root.addWidget(list_card)
        root.addStretch()

    def add_or_save_event(self):
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "警告", "請輸入行程標題！")
            return
        self.events = self.data_manager.load_events()
        if self.editing_event_id is not None:
            self.save_edited_event()
        else:
            self.add_new_event()

    def add_new_event(self):
        import uuid
        
        date_str = self.date_input.date().toString("yyyy-MM-dd")
        time_str = self.time_input.time().toString("HH:mm")
        event_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        is_past = datetime.now() > event_dt
        
        event = Event(
            id=uuid.uuid4().hex,
            title=self.title_input.text().strip(),
            date=date_str,
            time=time_str,
            description=self.desc_input.toPlainText().strip(),
            completed=self.completed_checkbox.isChecked(),
            notified=is_past 
        )
        self.events.append(event)
        self.finish_editing()

    def start_editing_event(self, item):
        event_id = item.data(Qt.UserRole)
        self.events = self.data_manager.load_events()
        event_to_edit = next((e for e in self.events if e.id == event_id), None)
        if event_to_edit:
            self.title_input.setText(event_to_edit.title)
            self.date_input.setDate(QDate.fromString(event_to_edit.date, "yyyy-MM-dd"))
            self.time_input.setTime(QTime.fromString(event_to_edit.time, "HH:mm"))
            self.desc_input.setText(event_to_edit.description)
            self.completed_checkbox.setChecked(event_to_edit.completed)
            self.editing_event_id = event_id
            self.add_btn.setText("儲存變更")
            self.cancel_btn.show()

    def save_edited_event(self):
        event_to_save = next((e for e in self.events if e.id == self.editing_event_id), None)
        if event_to_save:
            new_date = self.date_input.date().toString("yyyy-MM-dd")
            new_time = self.time_input.time().toString("HH:mm")
            
            event_dt = datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M")
            if datetime.now() > event_dt:
                event_to_save.notified = True
            elif event_to_save.notified: 
                event_to_save.notified = False

            event_to_save.title = self.title_input.text().strip()
            event_to_save.date = new_date
            event_to_save.time = new_time
            event_to_save.description = self.desc_input.toPlainText().strip()
            event_to_save.completed = self.completed_checkbox.isChecked()
            self.finish_editing()

    def cancel_edit(self):
        self.title_input.clear()
        self.desc_input.clear()
        self.date_input.setDate(QDate.currentDate())
        self.time_input.setTime(QTime.currentTime())
        self.completed_checkbox.setChecked(False)
        self.editing_event_id = None
        self.add_btn.setText("新增")
        self.cancel_btn.hide()

    def finish_editing(self):
        self.data_manager.save_events(self.events)
        self.update_event_list()
        self.cancel_edit()
        if self.calendar_window_getter:
            cw = self.calendar_window_getter()
            if cw and cw.isVisible():
                cw.refresh_events()
        if self.main_window:
            self.main_window.check_notifications()
            self.main_window.refresh_overview_events()
            # 通知統計視窗更新
            if hasattr(self.main_window, 'stats_window'):
                if self.main_window.stats_window and self.main_window.stats_window.isVisible():
                    self.main_window.stats_window.refresh_data()

    def delete_event(self):
        selected_items = self.event_list.selectedItems()
        if not selected_items: return
        event_id_to_delete = selected_items[0].data(Qt.UserRole)
        self.events = self.data_manager.load_events()
        self.events = [e for e in self.events if e.id != event_id_to_delete]
        self.finish_editing()

    def update_event_list(self):
        self.event_list.clear()
        active_events = [e for e in self.events if not e.completed]
        sorted_events = sorted(active_events, key=lambda x: f"{x.date} {x.time}")
        
        for e in sorted_events:
            if e.description:
                flat_desc = e.description.replace('\n', ' ')
                max_len = 10 
                if len(flat_desc) > max_len:
                    disp_desc = flat_desc[:max_len] + "……"
                else:
                    disp_desc = flat_desc
                item_text = f"{e.date} {e.time} - {e.title}: {disp_desc}"
            else:
                item_text = f"{e.date} {e.time} - {e.title}"
            
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, e.id)
            item.setToolTip(f"標題: {e.title}\n描述: {e.description}")
            self.event_list.addItem(item)

class PastEventsPage(QWidget):
    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.events = self.data_manager.load_events()
        self.current_date = QDate.currentDate()
        self._build_ui()
        self.refresh_list()
    
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignTop)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)
        title = QLabel("📜 過往行程")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        
        month_card = QGroupBox("選擇月份")
        month_layout = QHBoxLayout(month_card)
        self.prev_month_btn = QPushButton("◀")
        self.month_label = QLabel()
        self.month_label.setAlignment(Qt.AlignCenter)
        self.next_month_btn = QPushButton("▶")
        self.today_btn = QPushButton("本月")
        self.prev_month_btn.clicked.connect(self.prev_month)
        self.next_month_btn.clicked.connect(self.next_month)
        self.today_btn.clicked.connect(self.goto_current_month)
        month_layout.addWidget(self.prev_month_btn)
        month_layout.addWidget(self.month_label, 1)
        month_layout.addWidget(self.today_btn)
        month_layout.addWidget(self.next_month_btn)
        root.addWidget(month_card)
        
        list_card = QGroupBox("已完成行程")
        list_layout = QVBoxLayout(list_card)
        self.event_list = QListWidget()
        self.event_list.setWordWrap(True)
        self.stats_label = QLabel()
        self.stats_label.setAlignment(Qt.AlignCenter)
        self.stats_label.setStyleSheet("color: #7A5645; font-size: 12px;")
        list_layout.addWidget(self.event_list)
        list_layout.addWidget(self.stats_label)
        root.addWidget(list_card)
        root.addStretch()
        self.update_month_label()
    
    def update_month_label(self):
        self.month_label.setText(f"{self.current_date.year()}年 {self.current_date.month()}月")
    
    def prev_month(self):
        self.current_date = self.current_date.addMonths(-1)
        self.update_month_label()
        self.refresh_list()
    
    def next_month(self):
        self.current_date = self.current_date.addMonths(1)
        self.update_month_label()
        self.refresh_list()
    
    def goto_current_month(self):
        self.current_date = QDate.currentDate()
        self.update_month_label()
        self.refresh_list()
    
    def refresh_list(self):
        self.event_list.clear()
        self.events = self.data_manager.load_events()
        year = self.current_date.year()
        month = self.current_date.month()
        completed_events = [
            e for e in self.events 
            if e.completed and e.date.startswith(f"{year:04d}-{month:02d}")
        ]
        completed_events.sort(key=lambda x: f"{x.date} {x.time}")
        for e in completed_events:
            if e.description:
                item_text = f"✅ {e.date} {e.time} - {e.title}\n    📝 {e.description}"
            else:
                item_text = f"✅ {e.date} {e.time} - {e.title}"
            item = QListWidgetItem(item_text)
            item.setForeground(QColor("#7A5645"))
            self.event_list.addItem(item)
        self.stats_label.setText(f"本月已完成 {len(completed_events)} 個行程")

class WorkPage(QWidget):
    def __init__(self, data_manager, main_window=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.main_window = main_window
        self.work_records = self.data_manager.load_work_records()
        self.live_timer = QTimer(self)
        self.live_timer.timeout.connect(self._update_live_display)
        # 番茄鐘獨立計時器
        self.pomodoro_update_timer = QTimer(self)
        self.pomodoro_update_timer.timeout.connect(self._update_pomodoro_display)
        self._build_ui()
        self._refresh_ui_states()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignTop)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)
        title = QLabel("⏰ 工作打卡")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        
        status = QGroupBox("今日狀態")
        form = QFormLayout(status)
        self.today_total_label = QLabel("0.00 小時")
        self.current_status_label = QLabel("未開始工作")
        self.pomodoro_status_label = QLabel("未啟動")
        self.today_total_label.setObjectName("statusLabel")
        self.current_status_label.setObjectName("statusLabel")
        self.pomodoro_status_label.setObjectName("statusLabel")
        form.addRow("今日總工時:", self.today_total_label)
        form.addRow("目前狀態:", self.current_status_label)
        form.addRow("番茄鐘:", self.pomodoro_status_label)
        
        ops = QGroupBox("工作控制")
        h_layout = QHBoxLayout(ops)
        self.btn_toggle_work = QPushButton("▶️ 開始工作")
        self.btn_toggle_work.clicked.connect(self.toggle_work)
        
        self.btn_pomodoro = QPushButton("🍅 開始番茄鐘")
        if self.main_window:
            self.btn_pomodoro.clicked.connect(self.main_window.toggle_pomodoro)
            
        h_layout.addWidget(self.btn_toggle_work)
        h_layout.addWidget(self.btn_pomodoro)
        
        hist = QGroupBox("今日打卡記錄")
        hv = QVBoxLayout(hist)
        self.history_list = QListWidget()
        hv.addWidget(self.history_list)
        
        root.addWidget(status)
        root.addWidget(ops)
        root.addWidget(hist)
        root.addStretch()

    def _get_today_record(self) -> WorkRecord:
        today_str = datetime.now().strftime("%Y-%m-%d")
        return self.work_records.setdefault(today_str, WorkRecord(date=today_str))

    def _is_working(self) -> bool:
        rec = self._get_today_record()
        if not rec.sessions: return False
        return rec.sessions[-1].get('end') is None

    def toggle_work(self):
        if self._is_working():
            rec = self._get_today_record()
            rec.sessions[-1]['end'] = datetime.now().isoformat()
            self.live_timer.stop()
        else:
            rec = self._get_today_record()
            rec.sessions.append({'start': datetime.now().isoformat(), 'end': None})
            self.live_timer.start(1000)
        self.data_manager.save_work_records(self.work_records)
        self._refresh_ui_states()

    def _refresh_ui_states(self):
        self.work_records = self.data_manager.load_work_records()
        working = self._is_working()
        if working:
            self.btn_toggle_work.setText("⏹️ 結束工作")
            self.live_timer.start(1000)
        else:
            self.btn_toggle_work.setText("▶️ 開始工作")
            self.live_timer.stop()
        self._update_live_display()
        self._update_history_list()

        # 檢查番茄鐘狀態
        if self.main_window:
            self.main_window.update_work_status_label()
            # 如果番茄鐘正在運行，啟動計時器
            if self.main_window.pomodoro_state != "idle":
                self.pomodoro_update_timer.start(1000)
                self._update_pomodoro_display()
            else:
                self.pomodoro_update_timer.stop()
                self._update_pomodoro_display()

    def _update_live_display(self):
        rec = self._get_today_record()
        total_hours = rec.calculate_total_hours()
        status_text = ""
        if self._is_working():
            current_session_start = datetime.fromisoformat(rec.sessions[-1]['start'])
            current_duration = datetime.now() - current_session_start
            total_seconds_today = total_hours * 3600 + current_duration.total_seconds()
            s = int(current_duration.total_seconds())
            h, rem = divmod(s, 3600)
            m, s = divmod(rem, 60)
            timer_str = f"{h:02d}:{m:02d}:{s:02d}"
            status_text = f"工作中 (本次: {timer_str})"
            self.today_total_label.setText(f"{total_seconds_today / 3600:.2f} 小時")
        else:
            status_text = "閒置中" if rec.sessions else "未開始工作"
            self.today_total_label.setText(f"{total_hours:.2f} 小時")
        self.current_status_label.setText(status_text)

    def _update_pomodoro_display(self):
        """獨立的番茄鐘狀態更新方法"""
        if self.main_window:
            pomo_state = self.main_window.pomodoro_state
            pomo_end_time = self.main_window.pomodoro_end_time

            if pomo_state == "working":
                if pomo_end_time:
                    remaining = pomo_end_time - datetime.now()
                    if remaining.total_seconds() > 0:
                        minutes = int(remaining.total_seconds() // 60)
                        seconds = int(remaining.total_seconds() % 60)
                        self.pomodoro_status_label.setText(f"🍅 工作中 {minutes:02d}:{seconds:02d}")
                    else:
                        self.pomodoro_status_label.setText("🍅 工作中")
                else:
                    self.pomodoro_status_label.setText("🍅 工作中")
            elif pomo_state == "breaking":
                if pomo_end_time:
                    remaining = pomo_end_time - datetime.now()
                    if remaining.total_seconds() > 0:
                        minutes = int(remaining.total_seconds() // 60)
                        seconds = int(remaining.total_seconds() % 60)
                        self.pomodoro_status_label.setText(f"☕ 休息中 {minutes:02d}:{seconds:02d}")
                    else:
                        self.pomodoro_status_label.setText("☕ 休息中")
                else:
                    self.pomodoro_status_label.setText("☕ 休息中")
            else:
                self.pomodoro_status_label.setText("未啟動")
        else:
            self.pomodoro_status_label.setText("未啟動")

    def start_pomodoro_timer(self):
        """啟動番茄鐘計時器（由主窗口調用）"""
        self.pomodoro_update_timer.start(1000)  # 每秒更新一次
        self._update_pomodoro_display()  # 立即更新一次

    def stop_pomodoro_timer(self):
        """停止番茄鐘計時器（由主窗口調用）"""
        self.pomodoro_update_timer.stop()
        self._update_pomodoro_display()  # 最後更新一次
        
    def _update_history_list(self):
        self.history_list.clear()
        rec = self._get_today_record()
        if not rec.sessions:
            self.history_list.addItem("今日尚無打卡記錄")
            return
        for i, session in enumerate(rec.sessions):
            start_dt = datetime.fromisoformat(session['start'])
            start_str = start_dt.strftime("%H:%M:%S")
            if session.get('end'):
                end_dt = datetime.fromisoformat(session['end'])
                end_str = end_dt.strftime("%H:%M:%S")
                duration = end_dt - start_dt
                minutes = duration.total_seconds() / 60
                self.history_list.addItem(f"第 {i+1} 段: {start_str} - {end_str} ({minutes:.1f} 分鐘)")
            else:
                self.history_list.addItem(f"第 {i+1} 段: {start_str} - (工作中...)")

class SettingsPage(QWidget):
    def __init__(self, data_manager, on_settings_saved=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.settings = self.data_manager.load_settings()
        self.on_settings_saved = on_settings_saved
        self._build_ui()

    def _build_ui(self):
        from PySide6.QtWidgets import QSizePolicy
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollBar:vertical { width: 8px; }")
        
        content_widget = QWidget()
        content_widget.setAttribute(Qt.WA_TranslucentBackground)
        
        root = QVBoxLayout(content_widget)
        root.setAlignment(Qt.AlignTop) 
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)
        
        title = QLabel("⚙️ 設定")
        title.setObjectName("pageTitle")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        g0 = QGroupBox("系統")
        v0 = QVBoxLayout(g0)
        self.cb_startup = QCheckBox("開機時自動啟動 (僅限 Windows)")
        if sys.platform != 'win32':
            self.cb_startup.setEnabled(False)
        self.cb_startup.setChecked(is_startup_enabled())
        v0.addWidget(self.cb_startup)

        g1 = QGroupBox("喝水提醒")
        f1 = QHBoxLayout(g1)
        
        self.cb_water = QCheckBox("啟用喝水提醒")
        self.cb_water.setChecked(self.settings.water_reminder_enabled)
        f1.addWidget(self.cb_water)
        
        f1.addSpacing(20)
        
        f1.addWidget(QLabel("提醒間隔:"))
        
        self.spin_water = QSpinBox()
        self.spin_water.setRange(1, 480)
        self.spin_water.setSuffix(" 分鐘")
        self.spin_water.setValue(self.settings.water_reminder_interval)
        self.spin_water.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        f1.addWidget(self.spin_water)

        g2 = QGroupBox("番茄鐘")
        h2 = QHBoxLayout(g2)
        h2.addWidget(QLabel("工作:"))
        self.spin_work = QSpinBox()
        self.spin_work.setRange(1, 480)
        self.spin_work.setSuffix(" 分鐘")
        self.spin_work.setValue(self.settings.pomodoro_work_minutes)
        self.spin_work.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h2.addWidget(self.spin_work)
        
        h2.addSpacing(20)
        
        h2.addWidget(QLabel("休息:"))
        self.spin_break = QSpinBox()
        self.spin_break.setRange(1, 480)
        self.spin_break.setSuffix(" 分鐘")
        self.spin_break.setValue(self.settings.pomodoro_break_minutes)
        self.spin_break.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h2.addWidget(self.spin_break)

        g3 = QGroupBox("聲音")
        v3 = QVBoxLayout(g3)
        self.cb_sound = QCheckBox("啟用提醒聲音")
        self.cb_sound.setChecked(self.settings.sound_enabled)
        v3.addWidget(self.cb_sound)
        volume_layout = QHBoxLayout()
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self.settings.volume * 100))
        self.volume_label = QLabel()
        self.update_volume_label(self.volume_slider.value())
        self.volume_slider.valueChanged.connect(self.update_volume_label)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(self.volume_label)
        v3.addWidget(self.cb_sound)
        v3.addLayout(volume_layout)

        g4 = QGroupBox("任務")
        h4 = QHBoxLayout(g4)
        h4.addWidget(QLabel("過去任務顯示筆數:"))
        self.spin_max_completed_tasks = QSpinBox()
        self.spin_max_completed_tasks.setRange(1, 100)
        self.spin_max_completed_tasks.setSuffix(" 筆")
        self.spin_max_completed_tasks.setValue(self.settings.max_completed_tasks)
        self.spin_max_completed_tasks.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        h4.addWidget(self.spin_max_completed_tasks)

        for gb in (g0, g1, g2, g3, g4):
            gb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        btns = QHBoxLayout()
        btns.setAlignment(Qt.AlignHCenter)
        btn_save = QPushButton("儲存")
        btn_reset = QPushButton("重設為預設值")
        btn_save.setMinimumHeight(40); btn_reset.setMinimumHeight(40)
        btn_save.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_reset.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_save.clicked.connect(self.save_settings)
        btn_reset.clicked.connect(self.reset_settings)
        btns.addWidget(btn_save); btns.addWidget(btn_reset)

        root.addWidget(g0)
        root.addWidget(g1)
        root.addWidget(g2)
        root.addWidget(g3)
        root.addWidget(g4)
        root.addLayout(btns)
        root.addStretch()
        
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

    def update_volume_label(self, value):
        self.volume_label.setText(f"{value}%")

    def save_settings(self):
        startup_changed = set_startup(self.cb_startup.isChecked())
        s = self.settings
        s.water_reminder_enabled = self.cb_water.isChecked()
        s.water_reminder_interval = self.spin_water.value()
        s.pomodoro_work_minutes = self.spin_work.value()
        s.pomodoro_break_minutes = self.spin_break.value()
        s.sound_enabled = self.cb_sound.isChecked()
        s.volume = self.volume_slider.value() / 100.0
        s.max_completed_tasks = self.spin_max_completed_tasks.value()
        self.data_manager.save_settings(s)
        if startup_changed:
            QMessageBox.information(self, "成功", "設定已儲存！")
        else:
            QMessageBox.warning(self, "提示", "應用程式設定已儲存，但開機啟動項操作失敗（可能需要管理員權限）。")
        if self.on_settings_saved: self.on_settings_saved()

    def reset_settings(self):
        if QMessageBox.question(self, "確認", "確定要重設為預設值嗎？") == QMessageBox.Yes:
            self.settings = Settings()
            self.cb_water.setChecked(self.settings.water_reminder_enabled)
            self.spin_water.setValue(self.settings.water_reminder_interval)
            self.spin_work.setValue(self.settings.pomodoro_work_minutes)
            self.spin_break.setValue(self.settings.pomodoro_break_minutes)
            self.spin_max_completed_tasks.setValue(self.settings.max_completed_tasks)
            self.cb_sound.setChecked(self.settings.sound_enabled)
            self.cb_startup.setChecked(False)

class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, icon, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        if icon: self.setIcon(icon)
        self.menu = QMenu()
        show_action = QAction("顯示主視窗", self)
        show_action.triggered.connect(self.show_main_window)
        quit_action = QAction("結束程式", self)
        quit_action.triggered.connect(self.quit_application)
        self.menu.addAction(show_action)
        self.menu.addSeparator()
        self.menu.addAction(quit_action)
        self.setContextMenu(self.menu)
        self.activated.connect(self.on_tray_icon_activated)
        
    def show_main_window(self):
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()
        
    def quit_application(self):
        if self.main_window:
            self.main_window.close()
        else:
            QApplication.instance().quit()
        
    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_main_window()

class TimeManagerApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setStyle("Fusion")
        dpi = self.primaryScreen().logicalDotsPerInch() or 96
        scale = dpi / 96.0
        base_pt = int(10 * scale)
        data_manager = DataManager()
        theme = data_manager.load_settings().theme
        app_font = QFont(theme.font_family, base_pt)
        self.setFont(app_font)
        
        icon = QIcon(resource_path("icon.ico"))
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.setWindowIcon(icon)
        self.setQuitOnLastWindowClosed(False)
        
        self.tray_icon = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = SystemTrayIcon(icon, None, self)
            self.tray_icon.show()
        
        self.main_window = TabbedMainWindow(tray_icon=self.tray_icon)
        
        if self.tray_icon:
            self.tray_icon.main_window = self.main_window
            self.tray_icon.showMessage("CocoTimer", "程式已在系統托盤中運行", QSystemTrayIcon.Information, 3000)
        self.main_window.show()

def main():            
    required_packages = ['PySide6', 'python-dateutil']
    missing_packages = []
    for package in required_packages:
        try:
            if package == 'PySide6': import PySide6
            elif package == 'python-dateutil': import dateutil
        except ImportError: missing_packages.append(package)
    
    if missing_packages:
        print("缺少必要套件，請先安裝：")
        for pkg in missing_packages: print(f"pip install {pkg}")
        return
    
    optional_packages = {'zhdate': '農曆日期顯示'}
    for package, description in optional_packages.items():
        try: __import__(package)
        except ImportError: print(f"○ {package} 未安裝 - {description}功能將被簡化")
    
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = TimeManagerApp(sys.argv)
    if QSystemTrayIcon.isSystemTrayAvailable():
        app.tray_icon.main_window = app.main_window
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
