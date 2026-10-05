import os
import sys

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 可攜模式：資料放在程式旁邊。COCOTIMER_DATA_DIR 只用於測試。
DATA_DIR = os.environ.get("COCOTIMER_DATA_DIR") or os.path.join(BASE_DIR, "timemanager_data")


def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', BASE_DIR)
    return os.path.join(base_path, relative_path)
