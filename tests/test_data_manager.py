import json
import os

from cocotimer.data_manager import DataManager
from cocotimer.models import Event


def test_loads_v2_data(v2_data):
    dm = DataManager(v2_data)
    tasks = dm.load_tasks()
    assert [t.id for t in tasks] == ["task-1", "task-2"]
    assert tasks[0].get_total_price() == 1.2 * 5000 + 500
    assert [e.title for e in dm.load_events()] == ["出版社線上會議", "健身房"]
    assert round(dm.load_work_records()["2026-10-02"].calculate_total_hours(), 2) == 7.38
    assert dm.load_settings().clock_visible is True
    assert dm.problems == []


def test_save_and_reload_round_trip(v2_data):
    dm = DataManager(v2_data)
    events = dm.load_events()
    events.append(Event(id="evt-3", title="新行程", date="2026-10-05", time="09:00"))
    dm.save_events(events)
    on_disk = json.load(open(os.path.join(v2_data, "events.json"), encoding="utf-8"))
    assert [e["id"] for e in on_disk] == ["evt-1", "evt-2", "evt-3"]
    assert [e.id for e in DataManager(v2_data).load_events()] == ["evt-1", "evt-2", "evt-3"]


def test_returned_objects_do_not_leak_into_cache(v2_data):
    dm = DataManager(v2_data)
    tasks = dm.load_tasks()
    tasks[0].title = "changed but not saved"
    tasks[0].price_items.append({"name": "x", "unit_price": 1, "quantity": 1})
    fresh = dm.load_tasks()[0]
    assert fresh.title == "第三集封面"
    assert len(fresh.price_items) == 2


def test_instances_share_one_cache(v2_data):
    a, b = DataManager(v2_data), DataManager(v2_data)
    settings = a.load_settings()
    settings.volume = 0.3
    a.save_settings(settings)
    assert b.load_settings().volume == 0.3


def test_unknown_fields_and_bad_entries_are_not_lost(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "events.json").write_text(json.dumps([
        {"id": "1", "title": "ok", "date": "2026-10-03", "time": "10:00", "color": "red"},
        {"title": "沒有 id 的壞資料"},
    ], ensure_ascii=False), encoding="utf-8")
    dm = DataManager(str(folder))
    events = dm.load_events()
    assert [e.id for e in events] == ["1"]
    assert dm.problems and "不會被刪除" in dm.problems[0]
    dm.save_events(events)
    on_disk = json.load(open(folder / "events.json", encoding="utf-8"))
    assert on_disk[0]["color"] == "red"
    assert on_disk[1] == {"title": "沒有 id 的壞資料"}


def test_corrupt_window_state_is_recovered_silently(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "window_state.json").write_text('{"main_win', encoding="utf-8")
    dm = DataManager(str(folder))
    assert dm._window_state() == {}
    assert dm.problems == []
    assert any(n.startswith("window_state.json.corrupt-") for n in os.listdir(folder))
