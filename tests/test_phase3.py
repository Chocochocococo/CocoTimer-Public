from datetime import date, datetime

from cocotimer import billing, theme
from cocotimer import tasks as svc
from cocotimer.models import Settings, TaskItem, ThemeConfig
from cocotimer.storage import JsonFileStore
from cocotimer.storage.migrations import _v6_to_v7


def make_task(**kw):
    base = dict(id="t", project_name="p", title="x", due_date="2026-10-03", due_time="18:00")
    base.update(kw)
    return TaskItem(**base)


# --- 配色 ---

def test_untouched_v2_theme_upgrades_to_v3(tmp_path):
    store = JsonFileStore(str(tmp_path))
    store.write("settings.json", {"volume": 0.5, "theme": {**theme.V2_DEFAULT_COLORS, "font_family": "Noto Sans TC"}})
    _v6_to_v7(store)
    saved = store.read("settings.json", dict)
    assert saved["theme"]["bg_color"] == theme.PRESETS[theme.DEFAULT_PRESET]["bg_color"]
    assert saved["theme"]["font_family"] == "Noto Sans TC"
    assert saved["volume"] == 0.5


def test_customised_theme_is_kept(tmp_path):
    store = JsonFileStore(str(tmp_path))
    custom = {**theme.V2_DEFAULT_COLORS, "accent_color": "#123456"}
    store.write("settings.json", {"theme": custom})
    _v6_to_v7(store)
    saved = store.read("settings.json", dict)["theme"]
    assert saved["accent_color"] == "#123456"
    assert saved["bg_color"] == theme.V2_DEFAULT_COLORS["bg_color"]
    assert saved["surface_color"] == theme.PRESETS["v2 經典"]["surface_color"]


def test_new_users_get_v3_colors():
    assert Settings().theme.bg_color == theme.PRESETS[theme.DEFAULT_PRESET]["bg_color"]


def test_mix_and_stylesheet():
    assert theme.mix("#000000", "#FFFFFF", 0.5) == "#808080"
    css = theme.stylesheet(ThemeConfig())
    assert "QFrame#sidebar" in css and "#A3521F" in css
    big = ThemeConfig(base_font_size=12)
    assert "font-size: 17px" in theme.stylesheet(big)


# --- 今天頁的計算 ---

def test_due_info_labels():
    now = datetime(2026, 10, 3, 15, 0)
    assert svc.due_info(make_task(due_date="2026-10-02", due_time="20:00"), now) == ("逾期 1 天", "overdue")
    assert svc.due_info(make_task(due_date="2026-10-03", due_time="14:00"), now) == ("逾期 1 小時", "overdue")
    assert svc.due_info(make_task(due_time="18:00"), now) == ("剩 3 小時", "today")
    assert svc.due_info(make_task(due_time="15:30"), now) == ("剩 30 分鐘", "today")
    assert svc.due_info(make_task(due_date="2026-10-05"), now) == ("剩 2 天", "soon")
    assert svc.due_info(make_task(due_date="2026-10-08"), now) == ("剩 5 天", "normal")
    done = make_task()
    svc.set_status(done, svc.INVOICED, "2026-10-03")
    assert svc.due_info(done, now) == ("已請款", "done")


def test_upcoming_tasks_sorted_and_only_in_progress():
    tasks = [make_task(id="b", due_date="2026-10-05"), make_task(id="a", due_date="2026-10-01"),
             make_task(id="c", due_date="2026-10-02", status=svc.DELIVERED)]
    assert [t.id for t in svc.upcoming_tasks(tasks)] == ["a", "b"]


def test_month_income():
    item = [billing.new_item("x", "張", 1, 1000)]
    tasks = [
        make_task(id="paid", price_items=item, status=svc.PAID, paid_date="2026-10-02"),
        make_task(id="paid-last-month", price_items=item, status=svc.PAID, paid_date="2026-09-30"),
        make_task(id="expected", price_items=item, status=svc.INVOICED, payment_date="2026-10-20"),
        make_task(id="late", price_items=item, status=svc.DELIVERED, payment_date="2026-09-01", currency="USD"),
        make_task(id="working", price_items=item, payment_date="2026-10-20"),
    ]
    income = svc.month_income(tasks, 2026, 10, date(2026, 10, 3))
    assert income == {"paid": {"NTD": 1000.0}, "expected": {"NTD": 1000.0}, "overdue": {"USD": 1000.0}}


def test_billing_summary():
    profile = billing.default_weighting_profile()
    weighting = billing.weighting_from_profile(profile, {b["label"]: c for b, c in zip(profile["bands"], [2600, 1300, 700, 400])})
    task = make_task(price_items=[billing.new_item("插畫", "張", 1.2, 0, billing.WEIGHTED, weighting),
                                  billing.new_item("急件", "件", 500, 1)])
    assert svc.billing_summary(task) == "委託 5,000 → 計費 3,630 張、1 件"
    assert svc.billing_summary(make_task()) == ""


# --- 任務列表 ---

def _sample_tasks():
    item = lambda n: [billing.new_item("x", "張", 1, n)]
    a = make_task(id="a", title="插畫 A", client="星河", due_date="2026-10-05", price_items=item(100))
    b = make_task(id="b", title="上色 B", client="Lumen", due_date="2026-10-01", price_items=item(300), currency="USD")
    c = make_task(id="c", title="插畫 C", client="星河", due_date="2026-09-01", price_items=item(200))
    svc.set_status(c, svc.INVOICED, "2026-09-02")
    c.payment_date = "2026-09-30"
    d = make_task(id="d", title="舊案 D", due_date="2026-08-01", price_items=item(50))
    svc.set_status(d, svc.PAID, "2026-08-30")
    e = make_task(id="e", title="舊案 E", due_date="2026-07-01")
    svc.set_status(e, svc.PAID, "2026-07-30")
    return [a, b, c, d, e]


def test_task_list_filters_search_and_sort():
    tasks = _sample_tasks()
    ids = lambda r: [t.id for t in r[0]]
    assert ids(svc.task_list(tasks, "active")) == ["b", "a"]
    assert ids(svc.task_list(tasks, "active", sort="amount")) == ["b", "a"]
    assert ids(svc.task_list(tasks, "active", sort="client")) == ["b", "a"]
    assert ids(svc.task_list(tasks, "receivable")) == ["c"]
    assert ids(svc.task_list(tasks, "closed")) == ["d", "e"]  # 已結案：新的在前
    assert ids(svc.task_list(tasks, "all", query="插畫")) == ["c", "a"]
    assert ids(svc.task_list(tasks, "all", query="星河 插畫 C")) == ["c"]
    shown, hidden = svc.task_list(tasks, "closed", closed_limit=1)
    assert [t.id for t in shown] == ["d"] and hidden == 1


def test_counts_totals_and_payment_info():
    tasks = _sample_tasks()
    assert svc.group_counts(tasks) == {"active": 2, "receivable": 1, "closed": 2, "all": 5}
    assert svc.totals_by_currency(tasks[:3]) == {"NTD": 300.0, "USD": 300.0}
    c = tasks[2]
    assert svc.payment_info(c, date(2026, 10, 3)) == ("預計 9/30 收款 · 已過 3 天", "late")
    assert svc.payment_info(c, date(2026, 9, 30)) == ("預計 9/30 收款 · 今天", "soon")
    assert svc.payment_info(c, date(2026, 9, 1)) == ("預計 9/30 收款", "normal")
    assert svc.payment_info(tasks[0]) == ("", "")


def test_dark_preset_switches_semantic_colors_and_chips():
    dark = ThemeConfig(**theme.PRESETS["可可深色"])
    t = theme.tokens(dark)
    assert theme.is_dark(t) and not theme.is_dark(theme.tokens(ThemeConfig()))
    assert t["danger"] != theme.tokens(ThemeConfig())["danger"]
    css = theme.stylesheet(dark)
    assert theme.STATUS_COLORS_DARK["red"][1] in css and theme.STATUS_COLORS["red"][1] not in css
    assert 'QLabel[tone="danger"]' in css
