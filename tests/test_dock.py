from PySide6.QtCore import QRect

from cocotimer.models import Settings
from cocotimer.ui.dock import HANDLE_H, HANDLE_W, dock_width, handle_pos, handle_rect, panel_rect
from cocotimer.ui.hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, parse_hotkey

# 1920×1080 的螢幕，工作列在下面（可用高度 1040），第二個螢幕在右邊
AVAIL = QRect(0, 0, 1920, 1040)
SECOND = QRect(1920, 0, 1280, 984)


def test_panel_rect_sides_and_second_screen():
    assert panel_rect(AVAIL, "right", 420) == QRect(1500, 0, 420, 1040)
    assert panel_rect(AVAIL, "left", 420) == QRect(0, 0, 420, 1040)
    assert panel_rect(SECOND, "right", 420) == QRect(2780, 0, 420, 984)
    assert panel_rect(QRect(0, 0, 300, 500), "right", 420).width() == 300  # 不會超出螢幕


def test_dock_width_is_screen_percentage_with_minimum():
    assert dock_width(AVAIL, 25) == 480
    assert dock_width(QRect(0, 0, 2560, 1400), 25) == 640
    assert dock_width(QRect(0, 0, 1366, 728), 25) == 420  # 小螢幕不會比最小寬度窄
    assert dock_width(AVAIL, 10, minimum=500) == 500


def test_handle_rect_and_position_round_trip():
    r = handle_rect(AVAIL, "right", 0.5)
    assert (r.width(), r.height()) == (HANDLE_W, HANDLE_H)
    assert r.right() == AVAIL.right() and r.top() == (1040 - HANDLE_H) // 2
    assert handle_rect(SECOND, "left", 0).topLeft() == SECOND.topLeft()
    assert handle_rect(AVAIL, "right", 1).bottom() == AVAIL.bottom()
    assert handle_rect(AVAIL, "right", 5).bottom() == AVAIL.bottom()  # 超出範圍會夾回來
    assert abs(handle_pos(AVAIL, handle_rect(AVAIL, "right", 0.3).top()) - 0.3) < 0.01


def test_hotkey_parsing():
    assert parse_hotkey("Ctrl+Alt+C") == (MOD_CONTROL | MOD_ALT, ord("C"))
    assert parse_hotkey("Ctrl+Shift+F5") == (MOD_CONTROL | MOD_SHIFT, 0x74)
    assert parse_hotkey("Alt+1") == (MOD_ALT, ord("1"))
    for bad in ("", "C", "Shift+C", "Ctrl+Alt+Space", "Ctrl+A, Ctrl+B"):
        assert parse_hotkey(bad) is None


def test_old_settings_get_dock_defaults():
    s = Settings.from_dict({"volume": 0.5})
    assert s.dock_enabled is False and s.dock_side == "right" and s.dock_width_percent == 25
    assert s.hotkey_enabled is False and s.hotkey == "Ctrl+Alt+C"
