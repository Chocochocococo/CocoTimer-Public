from cocotimer import billing
from cocotimer import tasks as svc
from cocotimer.models import TaskItem


def make(**kw):
    base = dict(id="t", project_name="p", title="x", due_date="2026-10-03", due_time="18:00")
    base.update(kw)
    return TaskItem(**base)


def test_add_and_sum_focus():
    t = make()
    svc.add_focus(t, 1500, "2026-10-01")
    svc.add_focus(t, 900.6, "2026-10-01")
    svc.add_focus(t, 600, "2026-10-03")
    assert t.focus_log == {"2026-10-01": 2400, "2026-10-03": 600}
    assert svc.focus_seconds(t) == 3000
    assert svc.focus_seconds(t, start="2026-10-02") == 600
    assert svc.focus_seconds(t, end="2026-10-01") == 2400


def test_hourly_rate_needs_amount_and_ten_minutes():
    t = make(price_items=[billing.new_item("x", "字", 1, 3000)])
    assert svc.hourly_rate(t) is None
    svc.add_focus(t, 300, "2026-10-01")
    assert svc.hourly_rate(t) is None  # 不到 10 分鐘
    svc.add_focus(t, 7200 - 300, "2026-10-01")
    assert svc.hourly_rate(t) == 1500
    assert svc.hourly_rate(make(focus_log={"2026-10-01": 7200})) is None  # 沒有金額


def test_bad_focus_log_is_tolerated_and_survives_round_trip():
    t = TaskItem.from_dict({"id": "a", "project_name": "p", "title": "t", "due_date": "2026-01-01",
                            "due_time": "10:00", "focus_log": "壞掉的資料"})
    assert svc.focus_seconds(t) == 0
    svc.add_focus(t, 120, "2026-01-01")
    assert TaskItem.from_dict(t.to_dict()).focus_log == {"2026-01-01": 120}
    assert svc.focus_text(59) == "0 分鐘" and svc.focus_text(3720) == "1 小時 02 分"
