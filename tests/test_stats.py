import csv
from datetime import date, datetime

from cocotimer import billing, stats
from cocotimer import tasks as svc
from cocotimer.models import Event, TaskItem, WorkRecord


def make(id, amount=1000, currency="NTD", **kw):
    base = dict(id=id, project_name="p", title=id, due_date="2026-10-03", due_time="18:00", currency=currency,
                price_items=[billing.new_item("x", "字", 1, amount)])
    base.update(kw)
    return TaskItem(**base)


def sample():
    a = make("a", client="星河", status=svc.PAID, delivered_date="2026-09-20", paid_date="2026-10-05",
             focus_log={"2026-09-18": 3600, "2026-10-01": 1800})
    b = make("b", 500, "USD", client="Lumen", status=svc.INVOICED, delivered_date="2026-10-02",
             payment_date="2026-10-31")
    c = make("c", 2000, client="星河", status=svc.DELIVERED, due_date="2026-07-31", delivered_date="2026-08-01",
             payment_date="2026-09-30")
    d = make("d", 300, client="星河", status=svc.PAID, due_date="2026-02-28", delivered_date="2026-03-01",
             paid_date="2026-03-10")
    e = make("e", 800, due_date="2026-10-20")  # 進行中
    return [a, b, c, d, e]


def test_period_and_income():
    assert stats.period("month", 2026, 2) == ("2026-02-01", "2026-02-28")
    assert stats.period("year", 2026, 7) == ("2026-01-01", "2026-12-31")
    tasks = sample()
    start, end = stats.period("month", 2026, 10)
    assert stats.income(tasks, start, end) == {"NTD": 1000.0}
    assert stats.expected(tasks, start, end) == {"USD": 500.0}
    total, late = stats.receivable(tasks, date(2026, 10, 3))
    assert total == {"USD": 500.0, "NTD": 2000.0} and late == {"NTD": 2000.0}
    assert stats.income_by_month(tasks, 2026, "NTD")[2] == 300 and stats.income_by_month(tasks, 2026, "NTD")[9] == 1000
    assert stats.primary_currency({"USD": 500.0}, {"NTD": 1000.0}) == "NTD"
    assert stats.currencies_used(tasks) == ["NTD", "USD"]


def test_period_tasks_clients_and_focus():
    tasks = sample()
    start, end = stats.period("month", 2026, 10)
    assert [t.id for t in stats.period_tasks(tasks, start, end)] == ["a", "b", "e"]
    assert stats.delivered_count(tasks, start, end) == 1
    assert stats.focus_total(tasks, start, end) == 1800
    rows = stats.client_rows(tasks, start, end)
    assert [r["name"] for r in rows] == ["星河", "Lumen"]
    assert rows[0]["paid"] == {"NTD": 1000.0} and rows[0]["focus"] == 1800 and rows[1]["delivered"] == 1


def test_work_seconds():
    records = {"2026-10-01": WorkRecord(date="2026-10-01", sessions=[
                   {"start": "2026-10-01T09:00:00", "end": "2026-10-01T11:30:00"},
                   {"start": "2026-10-01T13:00:00", "end": None}]),
               "2026-09-30": WorkRecord(date="2026-09-30", sessions=[{"start": "bad"}])}
    now = datetime(2026, 10, 1, 14, 0)
    days = dict(stats.work_by_day(records, "2026-09-30", "2026-10-02", now))
    assert days == {"2026-09-30": 0.0, "2026-10-01": 3.5 * 3600, "2026-10-02": 0.0}
    assert stats.work_by_month(records, 2026, now)[9] == 3.5 * 3600


def test_export_tables_and_csv(tmp_path):
    tasks = sample()
    events = [Event(id="e1", title="會議", date="2026-10-02", time="10:00"),
              Event(id="e2", title="舊", date="2025-01-01", time="10:00")]
    records = {"2026-10-01": WorkRecord(date="2026-10-01", sessions=[
        {"start": "2026-10-01T09:00:00", "end": "2026-10-01T10:00:00"}])}
    tables = stats.export_tables(tasks, events, records, *stats.period("month", 2026, 10))
    assert len(tables["任務"][1]) == 3 and len(tables["行程"][1]) == 1 and tables["工時"][1][0][3] == 60.0
    row_a = next(r for r in tables["任務"][1] if r[2] == "a")
    assert row_a[stats.TASK_HEADERS.index("番茄鐘專注（小時）")] == 1.5
    assert row_a[stats.TASK_HEADERS.index("時薪")] == 667
    summary = {r[0]: r for r in tables["總計"][1]}
    assert summary["NTD"][1] == 1000.0 and summary["USD"][2] == 500.0
    everything = stats.export_tables(tasks, events, records)
    assert len(everything["任務"][1]) == 5 and len(everything["行程"][1]) == 2
    files = stats.write_csv_files(str(tmp_path / "統計.csv"), tables)
    assert sorted(p.split("_")[-1] for p in files) == ["任務.csv", "工時.csv", "總計.csv", "行程.csv"]
    with open(tmp_path / "統計_任務.csv", encoding="utf-8-sig") as f:
        assert next(csv.reader(f))[0] == "建立日期"
