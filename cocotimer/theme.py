"""配色與樣式表。

所有顏色都來自使用者的 ThemeConfig（外觀設定可以改），這裡只負責：
- 提供預設配色（presets）
- 從幾個基本顏色推算出其他需要的顏色（例如淡色強調、輸入框邊框）
- 產生整個主視窗共用的 Qt 樣式表

不依賴 Qt，方便測試。
"""
import hashlib
import os
import tempfile
from typing import Dict

# 介面元件用到的固定狀態色（不隨主題改變，維持足夠對比）
STATUS_COLORS = {
    "red": ("#9E2219", "#FBE3E0"),
    "amber": ("#7A4B00", "#FBEFD5"),
    "blue": ("#1F4F8A", "#E4EDF8"),
    "purple": ("#5B3E99", "#ECE6F7"),
    "green": ("#285E2A", "#E1F0DE"),
    "teal": ("#1C5E54", "#DCEFEA"),
    "gray": ("#5E4C40", "#F1EAE1"),
}
# 深色主題用的狀態標籤顏色（文字、底色）
STATUS_COLORS_DARK = {
    "red": ("#F7C4BE", "#4D2420"),
    "amber": ("#F5DDA8", "#4A3A1C"),
    "blue": ("#CFE0F5", "#2B3A4D"),
    "purple": ("#DCCFF5", "#3A2E52"),
    "green": ("#CDEBC8", "#25402A"),
    "teal": ("#C5EBE3", "#1F3F3A"),
    "gray": ("#D9CCBF", "#3A302A"),
}
SUCCESS = "#2F8A55"
DANGER = "#B3261E"
MONO_FONTS = "'DM Mono', 'Cascadia Mono', Consolas, 'Courier New', monospace"

PRESETS: Dict[str, dict] = {
    "v3 奶茶（預設）": {
        "bg_color": "#F8F4EE", "text_color": "#33261D", "btn_color": "#FFFFFF", "btn_hover": "#F6E7DA",
        "border_color": "#E6DCD0", "accent_color": "#A3521F", "weekend_color": "#B3261E",
        "other_month_color": "#B3A496", "event_highlight_color": "#F6E7DA",
        "surface_color": "#FFFFFF", "sidebar_color": "#F1EAE1", "muted_color": "#6E5B4E",
        "accent_text_color": "#FFFFFF",
    },
    "v2 經典": {
        "bg_color": "#FFF7ED", "text_color": "#5B3A29", "btn_color": "#F9EEE4", "btn_hover": "#F2D7C3",
        "border_color": "#EEDAC8", "accent_color": "#D4A373", "weekend_color": "#C83B3B",
        "other_month_color": "#B89A8C", "event_highlight_color": "#F2D7C3",
        "surface_color": "#FFFDF9", "sidebar_color": "#F9EEE4", "muted_color": "#7D5A47",
        "accent_text_color": "#3B2414",
    },
}
PRESETS["可可深色"] = {
    "bg_color": "#1C1714", "text_color": "#F2E9E0", "btn_color": "#2E2621", "btn_hover": "#3B3029",
    "border_color": "#3A312A", "accent_color": "#E08A4F", "weekend_color": "#F08A7E",
    "other_month_color": "#6E6158", "event_highlight_color": "#3D2E24",
    "surface_color": "#26201C", "sidebar_color": "#211B17", "muted_color": "#B5A596",
    "accent_text_color": "#1C1714",
}
DEFAULT_PRESET = "v3 奶茶（預設）"

# v2 的預設配色：升級時如果使用者從沒改過顏色，就換成 v3 的新配色
V2_DEFAULT_COLORS = {k: v for k, v in PRESETS["v2 經典"].items()
                     if k not in ("surface_color", "sidebar_color", "muted_color", "accent_text_color")}


def _rgb(hex_color: str):
    h = (hex_color or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (0, 0, 0)


def mix(a: str, b: str, t: float) -> str:
    """a 和 b 混色，t = 0 為 a、t = 1 為 b。"""
    ra, rb = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ra, rb))


def rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


def tokens(theme) -> Dict[str, str]:
    """從 ThemeConfig 推算出樣式表需要的所有顏色。"""
    t = {
        "ground": theme.bg_color,
        "surface": theme.surface_color,
        "sidebar": theme.sidebar_color,
        "ink": theme.text_color,
        "muted": theme.muted_color,
        "line": theme.border_color,
        "button": theme.btn_color,
        "button_hover": theme.btn_hover,
        "accent": theme.accent_color,
        "accent_text": theme.accent_text_color,
        "highlight": theme.event_highlight_color,
        "weekend": theme.weekend_color,
        "other_month": theme.other_month_color,
        "font": theme.font_family,
    }
    t["line_strong"] = mix(t["line"], t["ink"], 0.15)
    t["accent_soft"] = mix(t["accent"], t["surface"], 0.86)
    t["accent_hover"] = mix(t["accent"], t["ink"], 0.2)
    t["accent_deep"] = mix(t["accent"], t["ink"], 0.35)
    t["nav_hover"] = mix(t["sidebar"], t["surface"], 0.5)
    t["track"] = mix(t["sidebar"], t["line"], 0.5)
    dark = is_dark_color(t["ground"])
    t["dark"] = "1" if dark else ""
    # 有意義的文字顏色（逾期、快到期、完成），深色背景時換成亮一點的版本
    t["danger"] = "#F08A7E" if dark else "#9E2219"
    t["warn"] = "#E8B04A" if dark else "#7A4B00"
    t["success"] = "#6CCB8F" if dark else "#2F8A55"
    return t


def is_dark_color(hex_color: str) -> bool:
    r, g, b = _rgb(hex_color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.45


def is_dark(colors: Dict[str, str]) -> bool:
    return bool(colors.get("dark"))


def _svg_file(path_data: str, color: str, width: float = 2.2) -> str:
    """Qt 樣式表不能用 data: 網址的圖片，所以把小圖示寫成暫存資料夾裡的 SVG 檔再引用。"""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{path_data}" fill="none" '
           f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    folder = os.path.join(tempfile.gettempdir(), "cocotimer-ui")
    path = os.path.join(folder, hashlib.sha1(svg.encode()).hexdigest()[:16] + ".svg")
    if not os.path.exists(path):
        try:
            os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
        except OSError:
            return ""
    return path.replace("\\", "/")


def stylesheet(theme) -> str:
    t = tokens(theme)
    down, up = _svg_file("M6 9l6 6 6-6", t["muted"]), _svg_file("M6 15l6-6 6 6", t["muted"])
    check = _svg_file("M20 6L9 17l-5-5", t["accent_text"], 3)
    base_px = max(11, min(22, round(getattr(theme, "base_font_size", 10) * 1.4)))  # 預設 10pt → 14px
    chips = "\n".join(
        f'QLabel[chip="{name}"] {{ color: {fg}; background: {bg}; border-radius: 9px; padding: 2px 8px; font-size: 12px; font-weight: 700; }}'
        for name, (fg, bg) in (STATUS_COLORS_DARK if t["dark"] else STATUS_COLORS).items())
    return f"""
QWidget {{ color: {t['ink']}; font-family: '{t['font']}', 'Microsoft JhengHei', sans-serif; font-size: {base_px}px; }}
QMainWindow, QWidget#contentArea, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {t['ground']}; }}
QDialog {{ background: {t['ground']}; }}

QFrame#sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['line']}; }}
QLabel#appName {{ font-size: 17px; font-weight: 700; background: transparent; }}
QLabel#appLogo {{ background: {t['accent']}; color: {t['accent_text']}; border-radius: 10px; font-weight: 700; font-size: 15px; }}
QLabel#sidebarFooter {{ color: {t['muted']}; font-size: 12px; background: transparent; }}
QPushButton#navItem {{ background: transparent; border: none; border-radius: 10px; padding: 0 12px; min-height: 44px;
    text-align: left; color: {t['muted']}; font-weight: 500; }}
QPushButton#navItem:hover {{ background: {t['nav_hover']}; }}
QPushButton#navItem:checked {{ background: {t['surface']}; color: {t['ink']}; font-weight: 700; }}
QToolButton#iconButton {{ background: transparent; border: none; border-radius: 10px; min-width: 40px; min-height: 40px; }}
QToolButton#iconButton:hover {{ background: {t['nav_hover']}; }}

QLabel#pageTitle {{ font-size: 26px; font-weight: 700; }}
QLabel#pageEyebrow, QLabel[muted="true"] {{ color: {t['muted']}; }}
QLabel#pageEyebrow {{ font-size: 13px; font-weight: 500; }}
QLabel[role="h2"] {{ font-size: 15px; font-weight: 700; }}
QLabel[role="timer"] {{ font-family: {MONO_FONTS}; font-size: 48px; font-weight: 500; }}
QLabel[role="timerSmall"] {{ font-family: {MONO_FONTS}; font-size: 34px; font-weight: 500; }}
QLabel[role="money"] {{ font-size: 28px; font-weight: 700; }}
QLabel[role="mono"] {{ font-family: {MONO_FONTS}; }}
{chips}

QFrame[card="true"] {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 16px; }}
QFrame[card="true"] QLabel, QFrame[card="true"] QCheckBox {{ background: transparent; }}
QFrame[row="true"] {{ background: transparent; border: none; border-top: 1px solid {mix(t['line'], t['surface'], 0.4)}; }}

QPushButton {{ background: {t['button']}; color: {t['ink']}; border: 1px solid {t['line_strong']}; border-radius: 10px;
    padding: 8px 16px; min-height: 22px; font-weight: 500; }}
QPushButton:hover {{ background: {t['button_hover']}; }}
QPushButton:pressed {{ background: {t['line']}; }}
QPushButton:disabled {{ color: {t['muted']}; background: {t['ground']}; }}
QPushButton[primary="true"] {{ background: {t['accent']}; color: {t['accent_text']}; border: none; font-weight: 700; }}
QPushButton[primary="true"]:hover {{ background: {t['accent_hover']}; }}
QPushButton[danger="true"] {{ color: {t['danger']}; border-color: {mix(t['danger'], t['surface'], 0.6)}; }}
QPushButton[link="true"][danger="true"] {{ color: {t['danger']}; border: none; background: transparent; }}
QToolButton[textButton="true"] {{ background: {t['button']}; color: {t['ink']}; border: 1px solid {t['line_strong']}; border-radius: 10px;
    padding: 8px 14px; min-height: 22px; font-weight: 500; }}
QToolButton[textButton="true"]:hover {{ background: {t['button_hover']}; }}
QToolButton[textButton="true"]:pressed {{ background: {t['line']}; }}
QToolButton[textButton="true"][compact="true"] {{ padding: 8px 8px; }}
QToolButton[textButton="true"]::menu-indicator {{ image: none; width: 0; }}
QLabel[tone="danger"] {{ color: {t['danger']}; font-weight: 600; }}
QLabel[tone="warn"] {{ color: {t['warn']}; font-weight: 600; }}
QLabel[tone="success"] {{ color: {t['success']}; font-weight: 600; }}
QPushButton[pill="true"] {{ border-radius: 18px; padding: 6px 14px; }}
QPushButton[pill="true"]:checked {{ background: {t['accent_soft']}; border: 1px solid {t['accent']}; color: {t['accent_deep']}; font-weight: 700; }}
QPushButton[link="true"] {{ background: transparent; border: none; color: {t['accent']}; padding: 4px 6px; font-weight: 500; }}
QPushButton[link="true"]:hover {{ color: {t['accent_deep']}; text-decoration: underline; }}

QFrame[segmentBar="true"] {{ background: {t['sidebar']}; border: none; border-radius: 12px; }}
QPushButton[segment="true"] {{ background: transparent; border: none; border-radius: 9px; padding: 7px 14px; color: {t['muted']}; font-weight: 500; }}
QPushButton[segment="true"]:hover {{ background: {t['nav_hover']}; }}
QPushButton[segment="true"][compact="true"] {{ padding: 7px 6px; }}
QPushButton[segment="true"]:checked {{ background: {t['surface']}; color: {t['ink']}; font-weight: 700; }}
QPushButton[step="true"] {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 12px; padding: 8px 12px;
    text-align: left; color: {t['muted']}; font-weight: 500; }}
QPushButton[step="true"]:checked {{ background: {t['accent_soft']}; border: 2px solid {t['accent']}; color: {t['ink']}; font-weight: 700; }}
QTableWidget#taskTable {{ border: 1px solid {t['line']}; border-radius: 14px; }}
QTableWidget#taskTable::item {{ border-bottom: 1px solid {mix(t['line'], t['surface'], 0.4)}; }}
QTableWidget#taskTable::item:selected {{ background: {t['accent_soft']}; }}
QFrame#saveBar {{ background: transparent; border: none; border-top: 1px solid {t['line']}; }}
QListWidget#clientList {{ border: none; background: transparent; }}
QListWidget#clientList::item {{ padding: 8px 10px; border-radius: 8px; color: {t['ink']}; }}
QListWidget#clientList::item:hover {{ background: {t['nav_hover']}; }}
QListWidget#clientList::item:selected {{ background: {t['accent_soft']}; color: {t['ink']}; font-weight: 700; }}
QWidget[cell="true"] {{ background: transparent; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit, QComboBox, QTextEdit, QPlainTextEdit {{
    background: {t['surface']}; border: 1px solid {t['line_strong']}; border-radius: 9px; padding: 5px 9px; min-height: 22px;
    selection-background-color: {t['accent_soft']}; selection-color: {t['ink']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus, QComboBox:focus, QTextEdit:focus {{
    border: 1px solid {t['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled, QComboBox:disabled,
QTextEdit:disabled {{ background: {t['ground']}; color: {t['muted']}; border-color: {t['line']}; }}
QComboBox::drop-down, QDateEdit::drop-down, QDateTimeEdit::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right;
    width: 26px; border: none; background: transparent; }}
QComboBox::down-arrow, QDateEdit::down-arrow, QDateTimeEdit::down-arrow {{ image: url({down}); width: 12px; height: 12px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button, QDateEdit::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border: none; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button, QDateEdit::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border: none; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow, QDateEdit::up-arrow {{ image: url({up}); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow, QDateEdit::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['line']}; selection-background-color: {t['accent_soft']}; selection-color: {t['ink']}; }}


QTableWidget, QTableView, QListWidget, QTreeWidget, QTreeView {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 12px;
    gridline-color: {mix(t['line'], t['surface'], 0.4)}; alternate-background-color: {mix(t['ground'], t['surface'], 0.5)};
    selection-background-color: {t['accent_soft']}; selection-color: {t['ink']}; }}
QHeaderView::section {{ background: {t['surface']}; color: {t['muted']}; border: none; border-bottom: 1px solid {t['line']};
    padding: 8px 10px; font-size: 12px; font-weight: 500; }}

QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar::tab {{ background: transparent; color: {t['muted']}; padding: 8px 16px; margin-right: 4px; border-radius: 9px; font-weight: 500; }}
QTabBar::tab:selected {{ background: {t['surface']}; color: {t['ink']}; font-weight: 700; }}
QTabBar::tab:hover {{ background: {t['nav_hover']}; }}

QProgressBar {{ background: {t['track']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}
QProgressBar[danger="true"]::chunk {{ background: {t['danger']}; }}
QSlider::groove:horizontal {{ height: 6px; background: {t['track']}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {t['surface']}; border: 2px solid {t['accent']}; width: 14px; margin: -6px 0; border-radius: 9px; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid {t['line_strong']}; background: {t['surface']}; border-radius: 5px; }}
QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; image: url({check}); }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['line_strong']}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['line_strong']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}

QMenu {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 7px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['ink']}; }}
QToolTip {{ background: {t['surface']}; color: {t['ink']}; border: 1px solid {t['line']}; padding: 6px 8px; border-radius: 8px; }}
"""
