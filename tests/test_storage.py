import json
import os
from datetime import datetime, timedelta

from cocotimer.storage import JsonFileStore, daily_snapshot, migrate
from cocotimer.storage.backup import BACKUP_DIR, DAILY_KEEP
from cocotimer.storage.migrations import CURRENT_SCHEMA, detect_schema


def _corrupt(path, content='[{"id": "half-writ'):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# --- JsonFileStore ---

def test_write_keeps_previous_version_as_bak(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("a.json", [1])
    store.write("a.json", [2])
    assert store.read("a.json", list) == [2]
    assert json.load(open(tmp_path / "a.json.bak")) == [1]
    assert not os.path.exists(tmp_path / "a.json.tmp")


def test_corrupt_file_is_restored_from_bak(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("tasks.json", [{"id": "1"}])
    store.write("tasks.json", [{"id": "1"}, {"id": "2"}])
    _corrupt(tmp_path / "tasks.json")

    assert store.read("tasks.json", list) == [{"id": "1"}]
    assert store.problems and "已從備份" in store.problems[0]
    # 修好的資料已寫回正式檔，壞檔另存保留
    assert json.load(open(tmp_path / "tasks.json")) == [{"id": "1"}]
    assert any(n.startswith("tasks.json.corrupt-") for n in os.listdir(tmp_path))


def test_empty_file_counts_as_corrupt(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("window_state.json", {"main": 1})
    store.write("window_state.json", {"main": 2})
    _corrupt(tmp_path / "window_state.json", "")
    assert store.read("window_state.json", dict) == {"main": 1}


def test_corrupt_without_bak_is_kept_aside_not_deleted(tmp_path):
    _corrupt(tmp_path / "events.json")
    store = JsonFileStore(str(tmp_path))
    assert store.read("events.json", list) == []
    kept = [n for n in os.listdir(tmp_path) if n.startswith("events.json.corrupt-")]
    assert len(kept) == 1
    assert open(tmp_path / kept[0], encoding="utf-8").read().startswith('[{"id"')
    assert "沒有可用的備份" in store.problems[0]


def test_write_never_overwrites_good_bak_with_corrupt_file(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("a.json", ["good"])
    store.write("a.json", ["newer"])
    _corrupt(tmp_path / "a.json")
    store.write("a.json", ["newest"])
    assert json.load(open(tmp_path / "a.json.bak")) == ["good"]


def test_missing_file_returns_default_without_problems(tmp_path):
    store = JsonFileStore(str(tmp_path))
    assert store.read("nope.json", dict) == {}
    assert store.problems == []


# --- 備份 ---

def test_daily_snapshot_runs_once_per_day(tmp_path):
    JsonFileStore(str(tmp_path)).write("tasks.json", [])
    day = datetime(2026, 10, 3, 9, 0)
    assert daily_snapshot(str(tmp_path), day)
    assert daily_snapshot(str(tmp_path), day + timedelta(hours=5)) is None
    assert daily_snapshot(str(tmp_path), day + timedelta(days=1))


def test_daily_snapshots_are_pruned_but_upgrade_backups_kept(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("tasks.json", [])
    migrate_dir = os.path.join(tmp_path, BACKUP_DIR, "20200101-000000-before-v3")
    os.makedirs(migrate_dir)
    start = datetime(2026, 1, 1)
    for i in range(DAILY_KEEP + 5):
        daily_snapshot(str(tmp_path), start + timedelta(days=i))
    names = os.listdir(tmp_path / BACKUP_DIR)
    assert len([n for n in names if n.endswith("-daily")]) == DAILY_KEEP
    assert "20200101-000000-before-v3" in names


def test_snapshot_skips_empty_folder(tmp_path):
    assert daily_snapshot(str(tmp_path)) is None


# --- 資料格式升級 ---

def test_v2_folder_is_detected_and_upgraded(v2_data):
    store = JsonFileStore(v2_data)
    assert detect_schema(store) == 2
    assert migrate(store, "test") == 2
    assert detect_schema(store) == CURRENT_SCHEMA
    backups = os.listdir(os.path.join(v2_data, BACKUP_DIR))
    assert any(b.endswith(f"before-v{CURRENT_SCHEMA}") for b in backups)
    # 升級後原本的資料都還在
    tasks = store.read("tasks.json", list)
    assert [t["id"] for t in tasks] == ["task-1", "task-2"]
    assert tasks[0]["description"] == "實際數量 3630 件"


def test_upgrade_normalises_price_item_numbers(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("tasks.json", [{"id": "t", "price_items": [
        {"name": "a", "unit_price": "1.5", "quantity": "2"},
        {"name": "b", "unit_price": None},
        "garbage"]}, {"id": "u", "price_items": None}])
    migrate(store, "test")
    tasks = store.read("tasks.json", list)
    numbers = [(i["name"], i["unit_price"], i["quantity"]) for i in tasks[0]["price_items"]]
    assert numbers == [("a", 1.5, 2.0), ("b", 0.0, 1.0)]
    assert tasks[1]["price_items"] == []


def test_fresh_folder_starts_at_current_schema_without_backup(tmp_path):
    store = JsonFileStore(str(tmp_path))
    assert migrate(store, "test") == CURRENT_SCHEMA
    assert json.load(open(tmp_path / "meta.json"))["schema_version"] == CURRENT_SCHEMA
    assert not os.path.exists(tmp_path / BACKUP_DIR)


def test_newer_schema_is_left_alone(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("meta.json", {"schema_version": CURRENT_SCHEMA + 1})
    store.write("tasks.json", [{"id": "t", "price_items": [{"quantity": "2"}]}])
    migrate(store, "test")
    assert store.read("tasks.json", list)[0]["price_items"] == [{"quantity": "2"}]
    assert store.problems


def test_upgraded_old_tasks_get_estimated_status_dates(tmp_path):
    """v2 升級時判定為已收款／已交付的舊任務要有日期，統計才算得到。"""
    from cocotimer.storage.migrations import _v7_to_v8
    from datetime import date

    store = JsonFileStore(str(tmp_path))
    store.write("billing.json", {"payment_rule": {"settlement_months": 1, "payment_months": 1,
                                                  "payment_day": 10, "calendar_ids": []}})
    store.write("tasks.json", [
        {"id": "old", "status": "paid", "due_date": "2025-03-12", "paid_date": "", "delivered_date": ""},
        {"id": "recent", "status": "delivered", "due_date": "2026-09-30", "delivered_date": ""},
        {"id": "dated", "status": "paid", "due_date": "2025-01-05", "delivered_date": "2025-01-06",
         "invoiced_date": "2025-02-01", "paid_date": "2025-02-20"},
        {"id": "late", "status": "paid", "due_date": "2026-10-01", "paid_date": ""},
        {"id": "wip", "status": "in_progress", "due_date": "2025-03-12"}])
    _v7_to_v8(store, today=date(2026, 10, 5))
    tasks = {t["id"]: t for t in store.read("tasks.json", list)}
    old = tasks["old"]
    assert old["delivered_date"] == "2025-03-12"
    assert old["settlement_date"] == "2025-04-30"  # 交件次月月底結算
    assert old["paid_date"] == "2025-05-10"  # 結算次月 10 日收款，不會還是空白
    assert tasks["recent"]["delivered_date"] == "2026-09-30" and not tasks["recent"].get("paid_date")
    assert tasks["dated"]["paid_date"] == "2025-02-20"  # 已經有的日期不動
    assert tasks["late"]["paid_date"] == "2026-10-05"  # 不會晚於今天
    assert "delivered_date" not in tasks["wip"]
