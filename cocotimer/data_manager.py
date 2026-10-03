"""資料存取的入口。

所有視窗共用同一份記憶體快取：讀取不再每次都開檔案，寫入則立刻安全地寫到磁碟。
視窗位置在移動、縮放、隱藏時記錄，延遲半秒合併成一次寫入，程式結束或登出時強制寫入。
"""
import copy
from typing import Dict, List

from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, QObject, QTimer
from PySide6.QtGui import QGuiApplication

from . import __version__
from . import billing
from .models import BillingConfig, Client, Event, Settings, TaskItem, WorkRecord
from .paths import DATA_DIR
from .storage import JsonFileStore, daily_snapshot, migrate

WINDOW_STATE_FILE = "window_state.json"
WINDOW_STATE_FLUSH_MS = 500


class _Shared:
    """同一個資料夾只會有一份：快取、視窗狀態與延遲寫入計時器。"""

    def __init__(self, data_dir: str):
        self.store = JsonFileStore(data_dir)
        migrate(self.store, __version__)
        daily_snapshot(data_dir)
        self.cache: Dict[str, object] = {}
        self.versions: Dict[str, int] = {}  # 每次存檔就加一，用來判斷「資料有沒有變」
        self.unreadable: Dict[str, list] = {}
        self.window_state = None
        self.window_state_dirty = False
        self.flush_timer = None


_shared: Dict[str, _Shared] = {}


class _GeometryKeeper(QObject):
    """視窗移動、縮放、隱藏或關閉時記錄位置。"""
    EVENTS = (QEvent.Move, QEvent.Resize, QEvent.Hide, QEvent.Close)

    def __init__(self, data_manager: "DataManager", name: str, widget):
        super().__init__(widget)
        self.data_manager = data_manager
        self.name = name

    def eventFilter(self, obj, event):
        if event.type() in self.EVENTS:
            self.data_manager.save_window_geometry(self.name, obj)
        return False


class DataManager:
    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or DATA_DIR
        if self.data_dir not in _shared:
            _shared[self.data_dir] = _Shared(self.data_dir)
        self._s = _shared[self.data_dir]

    @property
    def problems(self) -> List[str]:
        return self._s.store.problems

    # --- 共用讀寫 ---

    def _get(self, name: str, default_factory):
        if name not in self._s.cache:
            self._s.cache[name] = self._s.store.read(name, default_factory)
        return copy.deepcopy(self._s.cache[name])

    def _put(self, name: str, data) -> None:
        self._s.store.write(name, data)
        self._s.cache[name] = copy.deepcopy(data)
        self._s.versions[name] = self._s.versions.get(name, 0) + 1

    def version(self, *names: str) -> tuple:
        """資料檔的修改次數（例如 version("tasks.json")）。數字沒變就表示內容沒變，可以沿用上次算好的結果。"""
        return tuple(self._s.versions.get(n, 0) for n in names)

    def _load_records(self, name: str, cls) -> list:
        """讀取清單型資料。缺少必要欄位的項目不會顯示，但會保留下來，存檔時原樣寫回。"""
        data = self._get(name, list)
        if not isinstance(data, list):
            return []
        required = cls.required_fields()
        records, unreadable = [], []
        for d in data:
            if isinstance(d, dict) and all(k in d for k in required):
                records.append(cls.from_dict(d))
            else:
                unreadable.append(d)
        if unreadable and name not in self._s.unreadable:
            self.problems.append(f"{name} 有 {len(unreadable)} 筆資料格式不正確，已略過顯示，但不會被刪除。")
        self._s.unreadable[name] = unreadable
        return records

    def _put_records(self, name: str, records: list) -> None:
        self._put(name, [r.to_dict() for r in records] + self._s.unreadable.get(name, []))

    # --- 行程 ---

    def save_events(self, events: List[Event]):
        self._put_records("events.json", events)

    def load_events(self) -> List[Event]:
        return self._load_records("events.json", Event)

    # --- 打卡 ---

    def save_work_records(self, records: Dict[str, WorkRecord]):
        self._put("work_records.json", {k: v.to_dict() for k, v in records.items()})

    def load_work_records(self) -> Dict[str, WorkRecord]:
        data = self._get("work_records.json", dict)
        if not isinstance(data, dict):
            return {}
        return {k: WorkRecord.from_dict({"date": k, **v})
                for k, v in data.items() if isinstance(v, dict)}

    # --- 任務 ---

    def save_tasks(self, tasks: List[TaskItem]):
        self._put_records("tasks.json", tasks)

    def load_tasks(self) -> List[TaskItem]:
        return self._load_records("tasks.json", TaskItem)

    # --- 客戶與計費設定 ---

    def save_clients(self, clients: List[Client]):
        self._put_records("clients.json", clients)

    def load_clients(self, include_archived: bool = True) -> List[Client]:
        clients = self._load_records("clients.json", Client)
        return clients if include_archived else [c for c in clients if not c.archived]

    def save_billing(self, config: BillingConfig):
        self._put("billing.json", config.to_dict())

    def load_billing(self) -> BillingConfig:
        data = self._get("billing.json", dict)
        config = BillingConfig.from_dict(data) if isinstance(data, dict) else BillingConfig()
        if not config.weighting_profiles:
            profile = billing.default_weighting_profile()
            config.weighting_profiles = [profile]
            config.default_weighting_profile_id = profile["id"]
            self.save_billing(config)
        return config

    # --- 假日行事曆 ---

    def save_holidays(self, calendars: List[dict]):
        self._put("holidays.json", {"calendars": calendars})

    def load_holidays(self) -> List[dict]:
        data = self._get("holidays.json", dict)
        calendars = data.get("calendars") if isinstance(data, dict) else None
        return [c for c in calendars if isinstance(c, dict) and isinstance(c.get("days"), dict)] \
            if isinstance(calendars, list) else []

    # --- 設定 ---

    def save_settings(self, settings: Settings):
        self._put("settings.json", settings.to_dict())

    def load_settings(self) -> Settings:
        data = self._get("settings.json", dict)
        return Settings.from_dict(data) if isinstance(data, dict) else Settings()

    # --- 視窗位置 ---

    def _window_state(self) -> dict:
        if self._s.window_state is None:
            # 視窗位置壞掉只會讓視窗回到預設位置，不需要跳出提醒
            known_problems = len(self.problems)
            data = self._s.store.read(WINDOW_STATE_FILE, dict)
            del self.problems[known_problems:]
            self._s.window_state = data if isinstance(data, dict) else {}
        return self._s.window_state

    def save_window_geometry(self, name: str, widget):
        if getattr(widget, "_cocotimer_geometry_paused", False):
            return  # 例如主視窗在側邊停靠模式時，不要用停靠的位置蓋掉一般模式的位置
        geo_hex = bytes(widget.saveGeometry().toHex()).decode()
        state = self._window_state()
        entry = state.get(name) if isinstance(state.get(name), dict) else {}
        if entry.get("geometry") == geo_hex:
            return
        state[name] = {**entry, "geometry": geo_hex}
        self._s.window_state_dirty = True
        self._schedule_flush()

    def restore_window_geometry(self, name: str, widget) -> bool:
        restored = False
        entry = self._window_state().get(name)
        if isinstance(entry, dict) and isinstance(entry.get("geometry"), str):
            restored = widget.restoreGeometry(QByteArray.fromHex(entry["geometry"].encode()))
            if restored:
                _keep_on_screen(widget)
        if not getattr(widget, "_cocotimer_geometry_kept", False):
            widget.installEventFilter(_GeometryKeeper(self, name, widget))
            widget._cocotimer_geometry_kept = True
        return restored

    def _schedule_flush(self):
        if QCoreApplication.instance() is None:
            self.flush()
            return
        if self._s.flush_timer is None:
            timer = QTimer()
            timer.setSingleShot(True)
            timer.setInterval(WINDOW_STATE_FLUSH_MS)
            timer.timeout.connect(self.flush)
            self._s.flush_timer = timer
        self._s.flush_timer.start()

    def flush(self):
        """把還沒寫入的視窗位置寫到磁碟。"""
        if self._s.window_state_dirty:
            self._s.window_state_dirty = False
            self._s.store.write(WINDOW_STATE_FILE, self._s.window_state)


def _keep_on_screen(widget):
    """還原的位置不在任何螢幕上時（例如拔掉外接螢幕），移到主螢幕中央。"""
    if QGuiApplication.screenAt(widget.geometry().center()) is not None:
        return
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    widget.resize(min(widget.width(), area.width()), min(widget.height(), area.height()))
    frame = widget.frameGeometry()
    frame.moveCenter(area.center())
    widget.move(frame.topLeft())
