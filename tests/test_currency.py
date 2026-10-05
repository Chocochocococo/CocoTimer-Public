from datetime import date

from cocotimer import currency, stats
from cocotimer.models import Client, Settings, TaskItem


def test_aliases_are_merged():
    assert currency.normalize("twd") == "NTD"
    assert currency.normalize(" 台幣 ") == "NTD"
    assert currency.normalize("") == "NTD"
    assert currency.normalize("rmb") == "CNY"
    assert currency.normalize("usd") == "USD"
    assert TaskItem(id="t", project_name="", title="", due_date="", due_time="", currency="TWD").currency == "NTD"
    assert Client(id="c", name="x", currency="twd").currency == "NTD"
    assert Settings(default_currency="twd").default_currency == "NTD"


def test_convert_and_cross_rates():
    table = {"base": "NTD", "rates": {"USD": 32.0, "JPY": 0.2, "EUR": "bad"}}
    total, missing = currency.convert({"NTD": 100, "USD": 10, "JPY": 1000, "EUR": 5}, "NTD", table)
    assert total == 100 + 320 + 200 and missing == ["EUR"]
    # 常用幣別換成 USD 也算得出來（經過 NTD 交叉換算）
    assert currency.rate("JPY", "USD", table) == 0.2 / 32
    assert currency.rate("NTD", "USD", table) == 1 / 32
    assert currency.rate("EUR", "USD", table) is None


def test_set_rate_rebases_to_current_default():
    table = {"base": "NTD", "rates": {"USD": 32.0}}
    new = currency.set_rate(table, "USD", "JPY", 0.0068)
    assert new["base"] == "USD"
    assert new["rates"]["NTD"] == round(1 / 32, 6) and new["rates"]["JPY"] == 0.0068
    assert currency.set_rate(new, "USD", "JPY", 0)["rates"].keys() == {"NTD"}


def test_average_months_skip_unfinished_and_empty_months():
    today = date(2026, 10, 5)
    assert stats.average_months("year", 2026, 1, "2025-06-01", today) == [f"2026-{m:02d}" for m in range(1, 10)]
    assert stats.average_months("year", 2026, 1, "2026-03-15", today)[0] == "2026-03"
    month = stats.average_months("month", 2026, 10, "2020-01-01", today)
    assert month[0] == "2025-10" and month[-1] == "2026-09" and len(month) == 12
    assert stats.average_months("month", 2026, 5, "2020-01-01", today)[-1] == "2026-05"
    assert stats.average_months("all", 2026, 10, "2026-10-01", today) == ["2026-10"]  # 只有本月時就算本月
    assert stats.months_period(["2026-01", "2026-02"]) == ("2026-01-01", "2026-02-28")
