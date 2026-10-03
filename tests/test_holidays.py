import json
import os
from datetime import date

from cocotimer import holidays
from cocotimer import payment_terms as pt
from cocotimer import tasks as svc
from cocotimer.data_manager import DataManager
from cocotimer.models import BillingConfig, TaskItem
from cocotimer.storage import JsonFileStore, migrate
from cocotimer.storage.migrations import _v5_to_v6

HERE = os.path.join(os.path.dirname(__file__), "fixtures", "holidays")


def calendar_from(name):
    days, _kind = holidays.parse_file(os.path.join(HERE, name))
    cal = holidays.new_calendar(name)
    holidays.merge(cal, days)
    return cal


# --- 匯入 ---

def test_taiwan_official_csv_in_big5():
    days, kind = holidays.parse_file(os.path.join(HERE, "taiwan_2026_sep_oct_big5.csv"))
    assert kind == "行政機關辦公日曆表"
    assert days["2026-10-09"] == {"name": "補假", "off": True}        # 週五補假
    assert days["2026-10-10"] == {"name": "國慶日", "off": True}      # 週六但有名稱
    assert days["2026-09-25"]["name"] == "中秋節"
    assert "2026-10-05" not in days                                   # 普通平日不存
    assert "2026-10-03" not in days                                   # 普通週末不存


def test_taiwan_csv_in_utf8_with_makeup_workday(tmp_path):
    path = tmp_path / "tw.csv"
    path.write_text("西元日期,星期,是否放假,備註\n20250208,六,0,補行上班\n20250127,一,2,調整放假\n",
                    encoding="utf-8-sig")
    days, _ = holidays.parse_file(str(path))
    assert days == {"2025-02-08": {"name": "補行上班", "off": False},
                    "2025-01-27": {"name": "調整放假", "off": True}}


def test_ics_with_ranges_folding_and_escapes():
    days, kind = holidays.parse_file(os.path.join(HERE, "japan_sample.ics"))
    assert kind == "iCalendar 行事曆"
    assert days["2026-10-12"]["name"] == "Sports Day"
    assert days["2026-11-03"]["name"] == "Culture Day, observed"
    new_year = [d for d in days if days[d]["name"] == "Year-end and New Year holidays"]
    assert new_year == ["2026-12-29", "2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03"]


def test_simple_csv_with_mixed_date_formats():
    days, kind = holidays.parse_file(os.path.join(HERE, "simple.csv"))
    assert kind == "日期清單"
    assert days == {"2027-02-05": {"name": "公司春節休假", "off": True},
                    "2027-02-06": {"name": "公司春節休假", "off": True},
                    "2027-02-20": {"name": "補班", "off": False}}


def test_json_records(tmp_path):
    path = tmp_path / "2026.json"
    path.write_text(json.dumps([{"date": "20261009", "week": "五", "isHoliday": True, "description": "補假"},
                                {"date": "20261012", "week": "一", "isHoliday": False, "description": ""}]),
                    encoding="utf-8")
    days, _ = holidays.parse_file(str(path))
    assert days == {"2026-10-09": {"name": "補假", "off": True}}


def test_merge_reports_added_and_updated():
    cal = holidays.new_calendar("x")
    assert holidays.merge(cal, {"2026-01-01": {"name": "a", "off": True}}) == (1, 0)
    assert holidays.merge(cal, {"2026-01-01": {"name": "b", "off": True},
                                "2026-01-02": {"name": "c", "off": True}}) == (1, 1)


# --- 查詢 ---

def test_is_off_uses_holidays_makeup_days_and_weekends():
    tw = holidays.taiwan_calendar()
    company = holidays.new_calendar("公司")
    holidays.merge(company, {"2026-10-13": {"name": "公司休假", "off": True},
                             "2026-10-17": {"name": "補班", "off": False}})
    is_off = holidays.make_is_off([tw, company], [tw["id"], company["id"]])
    assert is_off(date(2026, 10, 9))       # 補假（週五）
    assert not is_off(date(2026, 10, 12))  # 普通週一
    assert is_off(date(2026, 10, 13))      # 公司休假
    assert not is_off(date(2026, 10, 17))  # 公司補班（週六）
    assert is_off(date(2026, 10, 18))      # 普通週日
    only_tw = holidays.make_is_off([tw, company], [tw["id"]])
    assert not only_tw(date(2026, 10, 13))


def test_bundled_taiwan_data_and_missing_years():
    tw = holidays.taiwan_calendar()
    assert holidays.years(tw) == [2026, 2027]
    assert holidays.missing_years([tw], [tw["id"]], {2027, 2028}) == {"台灣國定假日": [2028]}
    assert holidays.missing_years([tw], [], {2028}) == {}


# --- 套用到結算與收款日 ---

def test_payment_moves_past_national_holidays():
    tw = holidays.taiwan_calendar()
    is_off = holidays.make_is_off([tw], [tw["id"]])
    # 1/31 結算，2/16（除夕）付款 → 順延跳過春節與週末 → 2/23
    rule = pt.normalize_rule({"payment_day": 16, "payment_weekend": pt.WEEKEND_NEXT})
    assert pt.compute_dates("2026-01-10", rule, is_off) == ("2026-01-31", "2026-02-23")
    assert pt.compute_dates("2026-01-10", rule) == ("2026-01-31", "2026-02-16")  # 只看六日時不會發現


def test_settlement_on_bridge_holiday_moves_back():
    tw = holidays.taiwan_calendar()
    rule = pt.normalize_rule({"settlement_day": 9, "settlement_weekend": pt.WEEKEND_PREVIOUS})
    assert pt.compute_dates("2026-10-05", rule, holidays.make_is_off([tw], [tw["id"]]))[0] == "2026-10-08"


def test_task_dates_use_calendars():
    tw = holidays.taiwan_calendar()
    config = BillingConfig(payment_rule={"payment_type": pt.DAYS_AFTER, "payment_days": 9,
                                         "payment_weekend": pt.WEEKEND_NEXT, "calendar_ids": [tw["id"]]})
    task = TaskItem(id="t", project_name="p", title="x", due_date="2026-09-10", due_time="18:00")
    svc.apply_task_data(task, {}, [], config=config, calendars=[tw])
    # 9/30 結算 + 9 天 = 10/9 補假 → 10/10、10/11 週末 → 10/12
    assert (task.settlement_date, task.payment_date) == ("2026-09-30", "2026-10-12")


# --- 資料升級與預設值 ---

def test_v5_to_v6_links_taiwan_calendar_and_recomputes(tmp_path):
    store = JsonFileStore(str(tmp_path))
    custom = {"payment_type": "days_after", "payment_days": 9, "payment_weekend": "next"}
    store.write("billing.json", {"payment_rule": {"payment_weekend": "next", "payment_day": 16}})
    store.write("clients.json", [{"id": "c1", "name": "A", "payment_rule": custom}, {"id": "c2", "name": "B"}])
    store.write("tasks.json", [
        {"id": "1", "client_id": "c1", "due_date": "2026-09-10", "settlement_date": "x", "payment_date": "x"},
        {"id": "2", "client_id": "c2", "due_date": "2026-01-10", "settlement_date": "x", "payment_date": "x"},
        {"id": "3", "client_id": "c2", "due_date": "2026-01-10", "status": "paid", "settlement_date": "keep", "payment_date": "keep"},
        {"id": "4", "due_date": "2026-01-10", "billing_dates_auto": False, "settlement_date": "keep", "payment_date": "keep"},
    ])
    _v5_to_v6(store)
    tw_id = store.read("holidays.json", dict)["calendars"][0]["id"]
    assert store.read("billing.json", dict)["payment_rule"]["calendar_ids"] == [tw_id]
    assert store.read("clients.json", list)[0]["payment_rule"]["calendar_ids"] == [tw_id]
    tasks = {t["id"]: (t["settlement_date"], t["payment_date"]) for t in store.read("tasks.json", list)}
    assert tasks == {"1": ("2026-09-30", "2026-10-12"), "2": ("2026-01-31", "2026-02-23"),
                     "3": ("keep", "keep"), "4": ("keep", "keep")}


def test_fresh_install_gets_taiwan_calendar_linked(tmp_path):
    dm = DataManager(str(tmp_path / "fresh"))
    calendars = dm.load_holidays()
    assert [c["name"] for c in calendars] == ["台灣國定假日"]
    assert dm.load_billing().payment_rule["calendar_ids"] == [calendars[0]["id"]]


def test_v2_data_upgrades_to_current_schema(v2_data):
    store = JsonFileStore(v2_data)
    migrate(store, "test")
    dm = DataManager(v2_data)
    assert dm.load_holidays()
    task = dm.load_tasks()[0]
    assert task.settlement_date and task.payment_date
