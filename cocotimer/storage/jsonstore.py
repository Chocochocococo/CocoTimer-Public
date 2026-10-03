"""安全的 JSON 檔案讀寫。

寫入：先寫暫存檔並確實寫入磁碟，再把舊檔複製成 ``.bak``，最後用暫存檔取代正式檔。
就算寫到一半斷電或被強制結束，正式檔要嘛是舊的、要嘛是新的，不會是壞掉的半成品。

讀取：正式檔讀不到或壞掉時，改讀 ``.bak``。兩個都壞掉時，把壞檔改名保留下來
（``*.corrupt-時間``），讓使用者還有機會手動救回，程式則以空資料繼續執行。
"""
import json
import os
import shutil
from datetime import datetime
from typing import Any, Callable, List


class JsonFileStore:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        # 讀取時發生的問題（給介面顯示用）
        self.problems: List[str] = []

    def path(self, name: str) -> str:
        return os.path.join(self.data_dir, name)

    def exists(self, name: str) -> bool:
        return os.path.exists(self.path(name)) or os.path.exists(self.path(name) + ".bak")

    def read(self, name: str, default_factory: Callable[[], Any]) -> Any:
        path = self.path(name)
        main_error = None
        if os.path.exists(path):
            try:
                return self._load(path)
            except (OSError, ValueError) as e:
                main_error = e

        bak = path + ".bak"
        if os.path.exists(bak):
            try:
                data = self._load(bak)
            except (OSError, ValueError):
                data = None
            else:
                if main_error is not None:
                    self._quarantine(path)
                    self.problems.append(f"{name} 已損壞，已從備份 {name}.bak 還原。")
                    self.write(name, data)
                return data

        if main_error is not None:
            kept = self._quarantine(path)
            self.problems.append(
                f"{name} 已損壞且沒有可用的備份，原檔已另存為 {os.path.basename(kept)}。")
        return default_factory()

    def write(self, name: str, data: Any) -> None:
        path = self.path(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            try:
                self._load(path)
            except (OSError, ValueError):
                pass  # 不要用壞掉的檔案覆蓋掉還能用的備份
            else:
                shutil.copy2(path, path + ".bak")
        os.replace(tmp, path)

    @staticmethod
    def _load(path: str) -> Any:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _quarantine(self, path: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = f"{path}.corrupt-{stamp}"
        try:
            os.replace(path, target)
        except OSError:
            pass
        return target
