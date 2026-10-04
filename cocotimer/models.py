"""資料結構。

每個資料類別都可以用 ``from_dict`` 從 JSON 讀進來、用 ``to_dict`` 寫回去：
- 缺少的欄位使用預設值；
- 不認識的欄位會保留在物件上，存檔時原樣寫回，不會因為版本差異而遺失資料。
"""
from dataclasses import MISSING, asdict, dataclass, field, fields
from datetime import datetime
from typing import Dict, List, Optional, TypedDict

from . import billing, payment_terms


class WorkSession(TypedDict):
    start: str
    end: Optional[str]


class Record:
    """提供容錯的 from_dict / to_dict。"""

    @classmethod
    def from_dict(cls, data: dict):
        known = {f.name for f in fields(cls)}
        obj = cls(**{k: v for k, v in data.items() if k in known})
        obj._extra = {k: v for k, v in data.items() if k not in known}
        return obj

    @classmethod
    def required_fields(cls) -> List[str]:
        return [f.name for f in fields(cls)
                if f.default is MISSING and f.default_factory is MISSING]

    def to_dict(self) -> dict:
        data = dict(getattr(self, "_extra", {}))
        data.update(asdict(self))
        return data


@dataclass
class Event(Record):
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
class TaskItem(Record):
    """工作任務"""
    id: str
    project_name: str  # 專案名稱
    title: str  # 任務標題
    due_date: str  # 交件日期（YYYY-MM-DD）
    due_time: str  # 交件時間（HH:MM）
    client: str = ""  # 客戶
    description: str = ""  # 描述
    completion: int = 0  # 完成度百分比（0-100）
    price_items: List[Dict] = field(default_factory=list)  # 價格項目列表
    currency: str = "NTD"  # 幣別（預設台幣）
    remind_before: int = 0  # 提前提醒分鐘數（0表示不提醒）
    created_date: str = ""  # 建立日期
    created_time: str = ""  # 建立時間
    notified_before: bool = False  # 是否已提前提醒
    notified_due: bool = False  # 是否已到期提醒
    client_id: str = ""  # 對應 clients.json 的客戶；client 欄位保留客戶名稱方便顯示
    status: str = "in_progress"  # in_progress / delivered / invoiced / paid
    delivered_date: str = ""  # 交付日期（YYYY-MM-DD）
    invoiced_date: str = ""  # 請款日期
    paid_date: str = ""  # 收款日期（實際收到款項的日期）
    settlement_date: str = ""  # 結算日（YYYY-MM-DD）
    payment_date: str = ""  # 預計收款日
    billing_dates_auto: bool = True  # 結算日／收款日依客戶規則自動計算
    focus_log: Dict[str, int] = field(default_factory=dict)  # 番茄鐘專注在這個任務的秒數，依日期記錄

    def get_total_price(self) -> float:
        """計算總價（依各項目的計費方式）"""
        return billing.items_total(self.price_items)

    def is_overdue(self) -> bool:
        """是否已逾期"""
        if self.completion >= 100:
            return False
        now = datetime.now()
        due_datetime_str = f"{self.due_date} {self.due_time}"
        try:
            due_datetime = datetime.strptime(due_datetime_str, "%Y-%m-%d %H:%M")
            return now > due_datetime
        except ValueError:
            return False


@dataclass
class WorkRecord(Record):
    date: str
    sessions: List[WorkSession] = field(default_factory=list)

    def calculate_total_hours(self) -> float:
        total_seconds = 0
        for session in self.sessions:
            if session.get('start') and session.get('end'):
                start_dt = datetime.fromisoformat(session['start'])
                end_dt = datetime.fromisoformat(session['end'])
                total_seconds += max(0.0, (end_dt - start_dt).total_seconds())  # 結束早於開始的紀錄不算成負的
        return total_seconds / 3600.0


@dataclass
class ThemeConfig(Record):
    """配色。預設值是 v3 的「奶茶」配色（見 theme.PRESETS）。"""
    bg_color: str = "#F8F4EE"          # 背景色
    text_color: str = "#33261D"        # 主要文字色 (平日日期)
    btn_color: str = "#FFFFFF"         # 按鈕背景
    btn_hover: str = "#F6E7DA"         # 按鈕懸停
    border_color: str = "#E6DCD0"      # 邊框顏色
    accent_color: str = "#A3521F"      # 強調色 (今天、主要按鈕)
    weekend_color: str = "#B3261E"     # 週末文字顏色
    other_month_color: str = "#B3A496" # 非本月日期顏色 (灰)
    event_highlight_color: str = "#F6E7DA" # 行程日期高亮色
    surface_color: str = "#FFFFFF"     # 卡片、輸入框底色
    sidebar_color: str = "#F1EAE1"     # 側邊欄底色
    muted_color: str = "#6E5B4E"       # 次要文字
    accent_text_color: str = "#FFFFFF" # 強調色上的文字
    font_family: str = "Noto Sans TC"
    base_font_size: int = 10
    font_bold: bool = False            # 字體是否粗體
    font_italic: bool = False          # 字體是否斜體
    font_underline: bool = False       # 字體是否底線
    font_strikeout: bool = False       # 字體是否刪除線
    font_weight: int = 400             # 字體粗細 (100-900, 400=normal, 700=bold)


@dataclass
class Settings(Record):
    water_reminder_interval: int = 15
    water_reminder_enabled: bool = True
    water_alert_style: str = "toast"  # 喝水提醒的方式：toast / card / fullscreen / swarm（見 reminders.WATER_STYLES）
    water_alert_scale: int = 100  # 提醒視窗大小（%）
    water_swarm_count: int = 8  # 「到處冒出來」時跳出幾個
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
    sidebar_collapsed: bool = False  # 側邊欄收合成圖示列
    minimize_to_tray: bool = True  # 最小化時縮到系統匣（False 則留在工作列）
    keep_floats_on_top: bool = True  # 切換視窗時讓懸浮工具重新回到最上層
    floats_locked: bool = False  # 鎖定懸浮工具的位置與大小（避免誤拖）
    floats_dark: bool = False  # 懸浮工具使用深色外觀
    floats_opacity: int = 80
    clock_gap: str = "normal"  # 懸浮時鐘的時間與日期間距：tight / normal / loose  # 懸浮工具背景的不透明度（%），文字不受影響
    week_strip_visible: bool = False
    mini_bar_visible: bool = False
    dock_enabled: bool = False  # 側邊停靠模式：主視窗收進螢幕邊緣的小把手
    dock_side: str = "right"  # right / left
    dock_screen: str = ""  # 停靠的螢幕名稱；空白或找不到時用主螢幕
    dock_handle_pos: float = 0.5  # 把手在螢幕邊緣的高度（0 = 最上面，1 = 最下面）
    dock_open_on_hover: bool = False  # 滑鼠停在把手上就展開（否則要點一下）
    dock_width_percent: int = 25  # 停靠時主視窗的寬度：螢幕可用寬度的百分比（至少 420 px）
    hotkey_enabled: bool = False  # 全域快捷鍵（僅限 Windows）
    hotkey: str = "Ctrl+Alt+C"
    pomodoro_task_id: str = ""  # 番茄鐘目前專注的任務
    sound_water: str = ""  # 自訂提醒音（資料夾 sounds/ 裡的檔名）；空白表示用內建音效
    sound_pomodoro: str = ""
    sound_reminder: str = ""
    default_currency: str = "NTD"  # 新任務、新客戶預設的幣別
    welcome_done: bool = False  # 第一次開啟時的歡迎引導已經看過（或略過）

    @classmethod
    def from_dict(cls, data: dict):
        data = dict(data)
        theme = data.get("theme")
        data["theme"] = ThemeConfig.from_dict(theme) if isinstance(theme, dict) else ThemeConfig()
        return super().from_dict(data)

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["theme"] = self.theme.to_dict()
        return data


@dataclass
class Client(Record):
    """客戶。rates 是這位客戶專屬的單價範本（見 billing.new_rate）。"""
    id: str
    name: str
    contact: str = ""
    email: str = ""
    currency: str = "NTD"
    payment_terms: str = ""  # 付款條件，例如「月結 30 天」
    notes: str = ""
    weighting_profile_id: str = ""  # 空白表示使用預設加權表
    rates: List[Dict] = field(default_factory=list)
    archived: bool = False
    payment_rule: Optional[Dict] = None  # 結算與收款規則；None 表示使用通用設定（見 payment_terms）


@dataclass
class BillingConfig(Record):
    """通用單價範本與加權表。"""
    rates: List[Dict] = field(default_factory=list)
    weighting_profiles: List[Dict] = field(default_factory=list)
    default_weighting_profile_id: str = ""
    payment_rule: Dict = field(default_factory=lambda: dict(payment_terms.DEFAULT_RULE))

    def rule_for(self, client: Optional["Client"]) -> dict:
        """客戶有自己的結算規則就用客戶的，否則用通用設定。"""
        rule = client.payment_rule if client and isinstance(client.payment_rule, dict) else self.payment_rule
        return payment_terms.normalize_rule(rule)

    def profile_for(self, client: Optional["Client"]) -> Optional[dict]:
        profile_id = (client.weighting_profile_id if client else "") or self.default_weighting_profile_id
        return (billing.find_profile(self.weighting_profiles, profile_id)
                or (self.weighting_profiles[0] if self.weighting_profiles else None))
