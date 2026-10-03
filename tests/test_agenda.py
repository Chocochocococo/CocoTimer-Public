from datetime import date, datetime

from cocotimer import agenda, holidays
from cocotimer import tasks as svc
from cocotimer.models import Event, TaskItem


def test_month_days_sunday_first_full_weeks():
    days = agenda.month_days(2026, 10)
    assert days[0] == date(2026, 9, 27) and days[-1] == date(2026, 10, 31)
    assert len(days) == 35
    feb = agenda.month_days(2026, 2)
    assert feb[0] == date(2026, 2, 1) and len(feb) == 28
    assert len(agenda.month_days(2026, 10, padding=False)) == 31
    assert agenda.month_days(2026, 12)[-1] == date(2027, 1, 2)


def test_day_items_order_and_kinds():
    now = datetime(2026, 10, 3, 15, 0)
    events = [Event(id="e1", title="會議", date="2026-10-03", time="10:00", completed=True),
              Event(id="e2", title="健身房", date="2026-10-03", time="19:30")]
    t1 = TaskItem(id="t1", project_name="p", title="第 3 章", due_date="2026-10-03", due_time="18:00", client="星河")
    t2 = TaskItem(id="t2", project_name="p", title="舊案", due_date="2026-10-03", due_time="09:00")
    t3 = TaskItem(id="t3", project_name="p", title="交了", due_date="2026-10-03", due_time="12:00")
    svc.set_status(t3, svc.DELIVERED, "2026-10-03")
    items = agenda.day_items(date(2026, 10, 3), events, [t1, t2, t3], now)
    assert [(i["time"], i["kind"]) for i in items] == [
        ("09:00", "overdue"), ("10:00", "done"), ("12:00", "done"), ("18:00", "due"), ("19:30", "event")]
    assert items[3]["detail"] == "星河 · 剩 3 小時"
    marks = agenda.month_items(2026, 10, events, [t1], now)
    assert list(marks) == ["2026-10-03"]


def test_holiday_names_and_off_days():
    tw = holidays.taiwan_calendar()
    days = agenda.month_days(2026, 10)
    names = agenda.holiday_names([tw], [tw["id"]], days)
    assert names["2026-10-09"]["name"] == "補假" and names["2026-10-10"]["name"] == "國慶日"
    off = agenda.off_days([tw], [tw["id"]], days)
    assert "2026-10-09" in off and "2026-10-12" not in off and "2026-10-11" in off
    assert agenda.holiday_names([tw], [], days) == {}
