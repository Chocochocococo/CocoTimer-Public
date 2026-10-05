"""讓懸浮工具保持在最上層（只在 Windows 上有作用）。

Windows 的「永遠置頂」只是把視窗放進置頂的那一群，群組裡誰在上面，看誰最後被點到。
其他置頂程式或工作列、Alt+Tab 都可能把懸浮工具擠下去，而且它不會自己回來。

這裡請 Windows 在「前景視窗換人」時通知我們（事件觸發，不是定時檢查），收到後把懸浮工具
重新放回最上層；重新置頂時不會搶走焦點。前景是全螢幕程式（遊戲、影片、簡報）時就讓位。
"""
import sys

from PySide6.QtCore import QTimer

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _WinEventProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                       wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
    _user32.SetWinEventHook.restype = wintypes.HANDLE
    _user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, _WinEventProc,
                                        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]

    EVENT_SYSTEM_FOREGROUND = 0x0003
    WINEVENT_OUTOFCONTEXT = 0x0000
    WINEVENT_SKIPOWNPROCESS = 0x0002
    HWND_TOPMOST = wintypes.HWND(-1)
    SWP_FLAGS = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
    MONITOR_DEFAULTTONEAREST = 2

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    def _is_fullscreen(hwnd) -> bool:
        if not hwnd or hwnd in (_user32.GetDesktopWindow(), _user32.GetShellWindow()):
            return False
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        monitor = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not monitor or not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False
        m = info.rcMonitor
        return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom


class TopmostKeeper:
    def __init__(self, windows_getter, enabled=True):
        self._windows_getter = windows_getter
        self._hook = None
        self._callback = None  # 要保留參照，否則會被回收而讓 Windows 呼叫到無效的函式
        self.set_enabled(enabled)

    def set_enabled(self, enabled: bool):
        if enabled:
            self._start()
        else:
            self.stop()

    def _start(self):
        if sys.platform != "win32" or self._hook:
            return
        try:
            self._callback = _WinEventProc(self._on_foreground_changed)
            self._hook = _user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None,
                                                 self._callback, 0, 0,
                                                 WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        except Exception:
            self._hook = None

    def stop(self):
        if sys.platform == "win32" and self._hook:
            try:
                _user32.UnhookWinEvent(self._hook)
            except Exception:
                pass
        self._hook = None

    def _on_foreground_changed(self, _hook, _event, hwnd, *_rest):
        try:
            if _is_fullscreen(hwnd):
                return
        except Exception:
            return
        # 稍等一下再置頂：前景視窗可能還在調整自己的層級
        QTimer.singleShot(120, self.reassert)

    def reassert(self):
        if sys.platform != "win32":
            return
        for window in self._windows_getter():
            try:
                _user32.SetWindowPos(int(window.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS)
            except Exception:
                continue


def fullscreen_on_same_monitor(widget) -> bool:
    """前景是全螢幕程式（遊戲、影片、簡報），而且跟 widget 在同一個螢幕上。只在 Windows 上有作用。"""
    if sys.platform != "win32":
        return False
    try:
        hwnd = _user32.GetForegroundWindow()
        if not _is_fullscreen(hwnd):
            return False
        mine = _user32.MonitorFromWindow(int(widget.winId()), MONITOR_DEFAULTTONEAREST)
        return _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST) == mine
    except Exception:
        return False
