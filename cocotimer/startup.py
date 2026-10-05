import sys
import os

from cocotimer.paths import BASE_DIR


APP_NAME = "CocoTimeManager_New"

def get_startup_command():
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'
    else:
        python_exe = sys.executable.replace("python.exe", "pythonw.exe")
        script_path = os.path.join(BASE_DIR, "main.py")
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
