import json
import os
from datetime import date

from cocotimer import tasks as svc
from cocotimer.data_manager import DataManager
from cocotimer.models import Client, TaskItem
from cocotimer.storage import JsonFileStore
from cocotimer.storage.migrations import _v3_to_v4, migrate


def make_task(**kw):
    base = dict(id="t", project_name="p", title="x", due_date="2026-10-03", due_time="18:00")
    base.update(kw)
    return TaskItem(**base)


# --- 狀態與完成度 ---

def test_status_beyond_in_progress_means_done():
    task = make_task(completion=40)
    svc.set_status(task, svc.INVOICED, "2026-10-03")
    assert task.completion == 100
    assert (task.delivered_date, task.invoiced_date, task.paid_date) == ("2026-10-03", "2026-10-03", "")


def test_going_back_clears_later_dates_but_keeps_earlier_ones():
    task = make_task()
    svc.set_status(task, svc.PAID, "2026-10-01")
    svc.set_status(task, svc.DELIVERED, "2026-10-05")
    assert (task.delivered_date, task.invoiced_date, task.paid_date) == ("2026-10-01", "", "")


def test_full_completion_marks_task_delivered():
    task = make_task(completion=100)
    svc.sync_status(task, "2026-10-03")
    assert task.status == svc.DELIVERED


def test_reminder_lowering_completion_reopens_task():
    task = make_task()
    svc.set_status(task, svc.DELIVERED, "2026-10-03")
    svc.update_completion(task, 80)
    assert (task.status, task.completion, task.delivered_date) == (svc.IN_PROGRESS, 80, "")


# --- 客戶 ---

def test_apply_task_data_links_or_creates_clients():
    clients = [Client(id="c1", name="星河出版")]
    task = make_task()
    changed = svc.apply_task_data(task, {"client": " 星河出版 ", "price_items": []}, clients)
    assert (task.client, task.client_id, changed) == ("星河出版", "c1", False)
    changed = svc.apply_task_data(task, {"client": "新客戶", "currency": "USD"}, clients)
    assert changed and clients[-1].name == "新客戶" and clients[-1].currency == "USD"
    assert task.client_id == clients[-1].id


def test_save_task_edit_creates_task_and_client(tmp_path):
    dm = DataManager(str(tmp_path / "d"))
    tasks = []
    data = {"project_name": "p", "title": "x", "due_date": "2026-10-03", "due_time": "18:00",
            "client": "Lumen Games", "currency": "USD", "description": "", "completion": 0,
            "price_items": [{"name": "LQA", "unit_price": 30, "quantity": 2}], "remind_before": 0,
            "status": svc.IN_PROGRESS}
    task = svc.save_task_edit(dm, tasks, None, data)
    assert DataManager(str(tmp_path / "d")).load_tasks()[0].get_total_price() == 60
    assert [c.name for c in dm.load_clients()] == ["Lumen Games"]
    assert task.client_id == dm.load_clients()[0].id


def test_client_summary_and_rename():
    client = Client(id="c1", name="星河出版")
    item = {"name": "x", "unit_price": 100, "quantity": 1}
    tasks = [make_task(id="1", client="星河出版", client_id="c1", price_items=[item], status=svc.DELIVERED),
             make_task(id="2", client="星河出版", client_id="c1", price_items=[item], status=svc.PAID),
             make_task(id="3", client="星河出版", client_id="c1"),
             make_task(id="4", client="別人", client_id="c2", price_items=[item], status=svc.PAID)]
    s = svc.client_summary(tasks, client)
    assert s == {"count": 3, "in_progress": 1, "receivable": {"NTD": 100.0}, "paid": {"NTD": 100.0}}
    client.name = "星河文化"
    assert svc.rename_client(tasks, client)
    assert [t.client for t in tasks] == ["星河文化"] * 3 + ["別人"]


# --- v3 → v4 升級 ---

def test_v3_to_v4_statuses_and_clients(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("tasks.json", [
        {"id": "a", "client": "星河出版", "currency": "NTD", "completion": 50, "due_date": "2026-10-10", "price_items": []},
        {"id": "b", "client": "星河出版 ", "currency": "NTD", "completion": 100, "due_date": "2026-09-20", "price_items": []},
        {"id": "c", "client": "Lumen", "currency": "USD", "completion": 100, "due_date": "2026-01-01",
         "price_items": [{"name": "x", "unit_price": 1, "quantity": 2}]},
        {"id": "d", "client": "", "completion": 100, "due_date": "壞掉的日期", "price_items": []},
    ])
    _v3_to_v4(store, today=date(2026, 10, 3))
    tasks = {t["id"]: t for t in store.read("tasks.json", list)}
    assert {k: t["status"] for k, t in tasks.items()} == {"a": "in_progress", "b": "delivered", "c": "paid", "d": "delivered"}
    clients = store.read("clients.json", list)
    assert [(c["name"], c["currency"]) for c in clients] == [("星河出版", "NTD"), ("Lumen", "USD")]
    assert tasks["a"]["client_id"] == tasks["b"]["client_id"] == clients[0]["id"]
    assert "client_id" not in tasks["d"]
    assert tasks["c"]["price_items"][0]["billing"] == "simple"
    billing_cfg = store.read("billing.json", dict)
    assert billing_cfg["default_weighting_profile_id"] == billing_cfg["weighting_profiles"][0]["id"]


def test_v3_to_v4_keeps_existing_client_currency(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("clients.json", [{"id": "c1", "name": "星河出版", "currency": "JPY"}])
    store.write("tasks.json", [{"id": "a", "client": "星河出版", "currency": "NTD", "completion": 0, "price_items": []}])
    _v3_to_v4(store)
    assert store.read("clients.json", list) == [{"id": "c1", "name": "星河出版", "currency": "JPY"}]
    assert store.read("tasks.json", list)[0]["client_id"] == "c1"


def test_v2_folder_upgrades_all_the_way(v2_data):
    store = JsonFileStore(v2_data)
    migrate(store, "test")
    tasks = json.load(open(os.path.join(v2_data, "tasks.json"), encoding="utf-8"))
    assert all("status" in t for t in tasks)
    dm = DataManager(v2_data)
    assert dm.load_tasks()[0].get_total_price() == 6500
    assert [c.name for c in dm.load_clients()] == ["星河出版"]
    assert dm.load_billing().weighting_profiles


def test_fresh_folder_gets_default_weighting_profile(tmp_path):
    dm = DataManager(str(tmp_path / "fresh"))
    config = dm.load_billing()
    assert config.profile_for(None)["id"] == config.default_weighting_profile_id
