"""CocoTimer 進入點。程式本體在 cocotimer/ 資料夾裡。"""
import importlib.util


def _check_packages() -> bool:
    required = {'PySide6': 'PySide6'}
    missing = [pkg for module, pkg in required.items() if importlib.util.find_spec(module) is None]
    if missing:
        print("缺少必要套件，請先安裝：")
        for pkg in missing:
            print(f"pip install {pkg}")
        return False
    if importlib.util.find_spec('zhdate') is None:
        print("○ zhdate 未安裝 - 農曆日期顯示功能將被簡化")
    return True


if __name__ == "__main__":
    if _check_packages():
        from cocotimer.app import main
        main()
