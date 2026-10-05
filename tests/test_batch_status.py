from cocotimer import tasks as svc
from cocotimer.models import TaskItem


def make(id, **kw):
    base = dict(id=id, project_name="p", title=id, due_date="2026-05-10", due_time="18:00", completion=100)
    base.update(kw)
    return TaskItem(**base)


def sample():
    a = make("a", client_id="c1", status=svc.DELIVERED, delivered_date="2026-05-10",
             settlement_date="2026-05-31", payment_date="2026-07-30")
    b = make("b", client_id="c2", status=svc.DELIVERED, due_date="2026-08-01", payment_date="2026-10-31")
    c = make("c", status=svc.INVOICED, due_date="2026-06-01", payment_date="2026-07-01")
    d = make("d", client_id="c1", status=svc.IN_PROGRESS, completion=40, due_date="2026-10-20")
    return [a, b, c, d]


def ids(tasks):
    return [t.id for t in tasks]


def test_batch_matches_filters():
    tasks = sample()
    receivable = {svc.DELIVERED, svc.INVOICED}
    assert ids(svc.batch_matches(tasks, statuses=receivable)) == ["a", "c", "b"]
    assert ids(svc.batch_matches(tasks, client_ids={"c1"})) == ["a", "d"]
    assert ids(svc.batch_matches(tasks, client_ids={svc.NO_CLIENT})) == ["c"]
    assert ids(svc.batch_matches(tasks, start="2026-06-01", end="2026-08-01")) == ["c", "b"]
    assert ids(svc.batch_matches(tasks, date_field="payment_date", end="2026-07-30")) == ["a", "c"]
    # 沒有結算日的任務，指定結算日期間時不算符合
    assert ids(svc.batch_matches(tasks, date_field="settlement_date", start="2026-01-01")) == ["a"]


def test_apply_batch_paid_uses_expected_dates_not_later_than_today():
    tasks = sample()
    before = svc.apply_batch_status(tasks[:3], svc.PAID, today="2026-10-03")
    a, b, c = tasks[:3]
    assert all(t.status == svc.PAID for t in (a, b, c))
    assert a.delivered_date == "2026-05-10"  # 原本就有的日期保留
    assert a.invoiced_date == "2026-05-31" and a.paid_date == "2026-07-30"
    assert b.paid_date == "2026-10-03"  # 預計收款日在未來 → 用今天
    assert c.invoiced_date == "2026-06-01" and c.paid_date == "2026-07-01"
    assert set(before) == {"a", "b", "c"} and before["a"]["status"] == svc.DELIVERED


def test_apply_batch_today_fixed_and_backwards():
    tasks = sample()
    svc.apply_batch_status([tasks[0]], svc.INVOICED, "today", today="2026-10-03")
    assert tasks[0].invoiced_date == "2026-10-03" and tasks[0].paid_date == ""
    svc.apply_batch_status([tasks[1]], svc.PAID, "fixed", "2026-09-15", today="2026-10-03")
    assert tasks[1].delivered_date == tasks[1].invoiced_date == tasks[1].paid_date == "2026-09-15"
    svc.apply_batch_status([tasks[2]], svc.DELIVERED, today="2026-10-03")
    assert tasks[2].status == svc.DELIVERED and tasks[2].invoiced_date == "" and tasks[2].paid_date == ""
    svc.apply_batch_status([tasks[2]], svc.IN_PROGRESS, today="2026-10-03")
    assert tasks[2].status == svc.IN_PROGRESS and tasks[2].completion == 90


def test_restore_tasks():
    tasks = sample()
    before = svc.apply_batch_status(tasks[:2], svc.PAID, today="2026-10-03")
    assert svc.restore_tasks(tasks, before) == 2
    assert tasks[0].status == svc.DELIVERED and tasks[0].paid_date == ""
    assert tasks[1].status == svc.DELIVERED
