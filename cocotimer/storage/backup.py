"""資料夾快照備份：存在 ``timemanager_data/backups/`` 底下。

- 每日備份：每天第一次啟動時備份一次，只保留最近 ``DAILY_KEEP`` 份。
- 升級前備份：資料格式升級前備份一次，永久保留，不會自動刪除。
"""
import os
import shutil
from datetime import datetime
from typing import Optional

BACKUP_DIR = "backups"
DAILY_KEEP = 14


def _data_files(data_dir: str):
    for name in sorted(os.listdir(data_dir)):
        if name.endswith(".json") and os.path.isfile(os.path.join(data_dir, name)):
            yield name


def snapshot(data_dir: str, label: str, now: Optional[datetime] = None) -> Optional[str]:
    """把資料夾裡的 .json 檔複製到一個新的備份資料夾；沒有資料可備份時回傳 None。"""
    names = list(_data_files(data_dir))
    if not names:
        return None
    now = now or datetime.now()
    target = os.path.join(data_dir, BACKUP_DIR, f"{now:%Y%m%d-%H%M%S}-{label}")
    suffix = 1
    while os.path.exists(target):
        suffix += 1
        target = os.path.join(data_dir, BACKUP_DIR, f"{now:%Y%m%d-%H%M%S}-{label}-{suffix}")
    os.makedirs(target)
    for name in names:
        shutil.copy2(os.path.join(data_dir, name), os.path.join(target, name))
    return target


def daily_snapshot(data_dir: str, now: Optional[datetime] = None) -> Optional[str]:
    now = now or datetime.now()
    root = os.path.join(data_dir, BACKUP_DIR)
    existing = sorted(d for d in os.listdir(root) if d.endswith("-daily")) if os.path.isdir(root) else []
    if any(d.startswith(f"{now:%Y%m%d}-") for d in existing):
        return None
    made = snapshot(data_dir, "daily", now)
    if made:
        existing.append(os.path.basename(made))
        for old in sorted(existing)[:-DAILY_KEEP]:
            shutil.rmtree(os.path.join(root, old), ignore_errors=True)
    return made
