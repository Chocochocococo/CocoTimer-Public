"""全域快捷鍵（僅限 Windows）：在任何程式裡按下就叫出或收起 CocoTimer。

用 Windows 的 RegisterHotKey 註冊，按下時 Windows 會送 WM_HOTKEY 給這個程式，
這裡用 Qt 的原生事件過濾器接收。其他系統上不會註冊，也不會出錯。
"""
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, Qt
from PySide6.QtGui import QKeySequence

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312
HOTKEY_ID = 0xC0C0


def parse_hotkey(text: str):
    """把 "Ctrl+Alt+C" 這樣的文字轉成 (Windows 修飾鍵, 虛擬按鍵碼)。無法使用時回傳 None。

    至少要有一個 Ctrl、Alt 或 Win，避免單按一個字母就被攔下來；按鍵只接受英文字母、數字和 F1～F24。"""
    seq = QKeySequence(text or "")
    if seq.count() != 1:
        return None
    combo = seq[0]
    mods_qt, key = combo.keyboardModifiers(), combo.key()
    mods = 0
    if mods_qt & Qt.ControlModifier:
        mods |= MOD_CONTROL
    if mods_qt & Qt.AltModifier:
        mods |= MOD_ALT
    if mods_qt & Qt.ShiftModifier:
        mods |= MOD_SHIFT
    if mods_qt & Qt.MetaModifier:
        mods |= MOD_WIN
    if not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return None
    k = int(key.value) if hasattr(key, "value") else int(key)
    if int(Qt.Key_A.value) <= k <= int(Qt.Key_Z.value) or int(Qt.Key_0.value) <= k <= int(Qt.Key_9.value):
        vk = k  # Qt 與 Windows 的英文字母、數字代碼相同
    elif int(Qt.Key_F1.value) <= k <= int(Qt.Key_F24.value):
        vk = 0x70 + k - int(Qt.Key_F1.value)
    else:
        return None
    return mods, vk


class _Filter(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
            try:
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.callback()
                    return True, 0
            except Exception:
                pass
        return False, 0


class GlobalHotkey:
    """register(text) 成功回傳 True；callback 會在 Qt 的主執行緒被呼叫。"""

    def __init__(self, callback):
        self.callback = callback
        self.registered = None
        self._filter = None

    def register(self, text: str) -> bool:
        self.unregister()
        if sys.platform != "win32":
            return False
        parsed = parse_hotkey(text)
        if parsed is None:
            return False
        mods, vk = parsed
        try:
            import ctypes
            if not ctypes.windll.user32.RegisterHotKey(None, HOTKEY_ID, mods | MOD_NOREPEAT, vk):
                return False  # 通常是被其他程式用掉了
        except Exception:
            return False
        if self._filter is None:
            self._filter = _Filter(lambda: self.callback())
            QCoreApplication.instance().installNativeEventFilter(self._filter)
        self.registered = text
        return True

    def unregister(self):
        if self.registered and sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                pass
        self.registered = None
