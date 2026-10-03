import pytest

from cocotimer import payment_terms as pt
from cocotimer import tasks as svc
from cocotimer.models import BillingConfig, Client, TaskItem
from cocotimer.storage import JsonFileStore
from cocotimer.storage.migrations import _v4_to_v5


def rule(**kw):
    return pt.normalize_rule({**pt.DEFAULT_RULE, **kw})


@pytest.mark.parametrize("due,settled,paid", [
    ("2026-10-03", "2026-10-31", "2026-11-01"),   # 預設：月底結算、次月 1 日收款
    ("2026-10-31", "2026-10-31", "2026-11-01"),   # 月底當天交件仍是當月結算
    ("2026-12-15", "2026-12-31", "2027-01-01"),   # 跨年
    ("2026-02-10", "2026-02-28", "2026-03-01"),   # 2 月月底
])
def test_default_rule(due, settled, paid):
    assert pt.compute_dates(due, None) == (settled, paid)


def test_cutoff_day_moves_late_tasks_to_next_month():
    r = rule(settlement_day=25)
    assert pt.compute_dates("2026-10-25", r)[0] == "2026-10-25"
    assert pt.compute_dates("2026-10-26", r)[0] == "2026-11-25"


def test_sixty_days_after_settlement():
    assert pt.compute_dates("2026-10-03", rule(payment_type=pt.DAYS_AFTER, payment_days=60)) == ("2026-10-31", "2026-12-30")


def test_month_day_payment_clamps_to_month_end():
    # 次月 31 日，但 11 月只有 30 天
    assert pt.compute_dates("2026-10-03", rule(payment_day=31))[1] == "2026-11-30"
    # 次次月月底
    assert pt.compute_dates("2026-10-03", rule(payment_months=2, payment_day=0))[1] == "2026-12-31"


def test_same_month_payment_already_passed_rolls_forward():
    # 當月 10 日付款，但月底才結算 → 次月 10 日
    assert pt.compute_dates("2026-10-03", rule(payment_months=0, payment_day=10))[1] == "2026-11-10"


def test_weekend_adjustment():
    # 2026-10-31 是星期六，2026-11-01 是星期日
    assert pt.compute_dates("2026-10-03", rule(settlement_weekend=pt.WEEKEND_PREVIOUS))[0] == "2026-10-30"
    assert pt.compute_dates("2026-10-03", rule(settlement_weekend=pt.WEEKEND_NEXT))[0] == "2026-11-02"
    assert pt.compute_dates("2026-10-03", rule(payment_weekend=pt.WEEKEND_NEXT))[1] == "2026-11-02"
    assert pt.compute_dates("2026-10-03", rule(payment_weekend=pt.WEEKEND_PREVIOUS))[1] == "2026-10-30"


def test_bad_dates_and_rules_are_tolerated():
    assert pt.compute_dates("not a date", None) == ("", "")
    assert pt.normalize_rule({"settlement_day": "x", "payment_type": "??", "payment_weekend": 3}) == pt.DEFAULT_RULE


def test_describe_rule():
    assert pt.describe_rule(None) == "每月月底結算，次月 1 日收款"
    assert pt.describe_rule(rule(payment_type=pt.DAYS_AFTER, payment_weekend=pt.WEEKEND_NEXT)) == \
        "每月月底結算，結算後 60 天收款（遇假日順延到下一個工作日）"


def make_task(**kw):
    base = dict(id="t", project_name="p", title="x", due_date="2026-10-03", due_time="18:00")
    base.update(kw)
    return TaskItem(**base)


def test_task_dates_follow_client_rule_or_general_default():
    config = BillingConfig()
    client = Client(id="c1", name="A", payment_rule=rule(payment_type=pt.DAYS_AFTER))
    task = make_task()
    svc.apply_task_data(task, {"client": "A"}, [client], config=config)
    assert (task.settlement_date, task.payment_date) == ("2026-10-31", "2026-12-30")
    svc.apply_task_data(task, {"client": "B"}, [client], config=config)
    assert (task.settlement_date, task.payment_date) == ("2026-10-31", "2026-11-01")


def test_manual_dates_are_kept():
    task = make_task()
    svc.apply_task_data(task, {"billing_dates_auto": False, "settlement_date": "2026-11-15",
                               "payment_date": "2027-01-15"}, [], config=BillingConfig())
    assert (task.settlement_date, task.payment_date) == ("2026-11-15", "2027-01-15")


def test_rule_change_recomputes_unpaid_auto_tasks_only():
    client = Client(id="c1", name="A")
    config = BillingConfig()
    tasks = [make_task(id="1", client_id="c1"), make_task(id="2", client_id="c1", status=svc.PAID),
             make_task(id="3", client_id="c1", billing_dates_auto=False, settlement_date="x", payment_date="y")]
    client.payment_rule = rule(payment_type=pt.DAYS_AFTER, payment_days=30)
    assert svc.recompute_billing_dates(tasks, [client], config)
    assert tasks[0].payment_date == "2026-11-30"
    assert tasks[1].payment_date == ""
    assert (tasks[2].settlement_date, tasks[2].payment_date) == ("x", "y")


def test_v4_to_v5_fills_dates_with_default_rule(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("billing.json", {"rates": []})
    store.write("tasks.json", [{"id": "a", "due_date": "2026-10-03"}, {"id": "b", "due_date": ""},
                               {"id": "c", "due_date": "2026-10-03", "settlement_date": "keep"}])
    _v4_to_v5(store)
    tasks = store.read("tasks.json", list)
    assert (tasks[0]["settlement_date"], tasks[0]["payment_date"]) == ("2026-10-31", "2026-11-01")
    assert tasks[1]["settlement_date"] == ""
    assert tasks[2]["settlement_date"] == "keep"
    assert store.read("billing.json", dict)["payment_rule"] == pt.DEFAULT_RULE


def test_new_task_defaults(tmp_path):
    from cocotimer.data_manager import DataManager
    dm = DataManager(str(tmp_path / "d"))
    data = {"project_name": "p", "title": "x", "due_date": "2026-12-15", "due_time": "18:00", "client": ""}
    task = svc.save_task_edit(dm, [], None, data)
    assert (task.settlement_date, task.payment_date, task.billing_dates_auto) == ("2026-12-31", "2027-01-01", True)
