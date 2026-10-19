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


# --- 中間交件 ---

NOW = __import__("datetime").datetime(2026, 10, 19, 12, 0)


def test_next_deadline_is_earliest_pending_milestone():
    task = make_task(due_date="2026-10-30", due_time="18:00", milestones=[
        {"id": "b", "date": "2026-10-25", "time": "18:00", "name": "", "done": False},
        {"id": "a", "date": "2026-10-20", "time": "12:00", "name": "草稿", "done": False}])
    task.milestones = svc.normalize_milestones(task.milestones, now=NOW)
    assert [m["id"] for m in task.milestones] == ["a", "b"]
    assert svc.next_deadline(task)[:2] == ("2026-10-20", "12:00")
    assert svc.due_info(task, NOW) == ("草稿 · 剩 1 天", "soon")
    svc.set_milestone_done(task, "a")
    assert svc.due_info(task, NOW) == ("中間交件 2 · 剩 6 天", "normal")
    svc.set_milestone_done(task, "b")
    assert svc.next_deadline(task) == ("2026-10-30", "18:00", None)
    assert svc.due_info(task, NOW) == ("剩 11 天", "normal")


def test_overdue_milestone_makes_task_overdue_and_sorts_first():
    late = make_task(id="late", due_date="2026-11-30", milestones=[
        {"id": "m", "date": "2026-10-18", "time": "18:00", "done": False}])
    plain = make_task(id="plain", due_date="2026-10-21")
    assert svc.due_info(late, NOW)[1] == "overdue"
    assert [t.id for t in svc.upcoming_tasks([plain, late])] == ["late", "plain"]
    svc.set_status(late, svc.DELIVERED, "2026-10-19")
    assert svc.next_deadline(late)[2] is None  # 交付之後就不看中間交件


def test_editing_times_resets_reminders_but_not_for_past_ones():
    task = make_task(due_date="2026-10-25", due_time="18:00", remind_before=30,
                     notified_before=True, notified_due=False)
    svc.apply_task_data(task, {"milestones": [{"date": "2026-10-20", "time": "10:00", "name": "線稿"},
                                              {"date": "2026-10-10", "time": "10:00", "name": "草稿", "done": True}]},
                        [], now=NOW)
    old, new = task.milestones
    assert old["notified_due"] and not new["notified_due"] and not new["notified_before"]
    assert task.notified_before  # 交件時間沒改，提醒紀錄不動
    new["notified_before"] = True
    svc.apply_task_data(task, {"milestones": [dict(m) for m in task.milestones]}, [], now=NOW)
    assert task.milestones[1]["notified_before"]  # 沒改時間就保留
    svc.apply_task_data(task, {"milestones": [dict(m) for m in task.milestones], "due_date": "2026-10-28"}, [], now=NOW)
    assert not task.notified_before and not task.notified_due  # 延後交件，提醒重新來過
    assert task.milestones[1]["notified_before"]
    svc.apply_task_data(task, {"remind_before": 60}, [], now=NOW)
    assert not task.milestones[1]["notified_before"]


def test_calendar_shows_milestones():
    from cocotimer import agenda
    task = make_task(title="封面", due_date="2026-10-30", milestones=svc.normalize_milestones([
        {"date": "2026-10-20", "time": "12:00", "name": "草稿"},
        {"date": "2026-10-22", "time": "12:00", "name": "線稿", "done": True}], now=NOW))
    items = agenda.month_items(2026, 10, [], [task], now=NOW)
    assert [(i["title"], i["kind"]) for i in items["2026-10-20"]] == [("封面（草稿）", "due")]
    assert items["2026-10-22"][0]["kind"] == "done"
    assert items["2026-10-30"][0]["title"] == "封面（最後交件）"
    assert items["2026-10-30"][0]["detail"] == "剩 11 天"


def test_old_data_without_milestones_still_loads():
    task = TaskItem.from_dict({"id": "t", "project_name": "p", "title": "x", "due_date": "2026-10-03", "due_time": "18:00"})
    assert task.milestones == [] and svc.next_deadline(task) == ("2026-10-03", "18:00", None)
