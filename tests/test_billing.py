import copy

import pytest

from cocotimer import billing

PROFILE = {"id": "p1", "name": "常用", "round_to_integer": True, "bands": [
    {"label": "全新製作", "rate": 1.0}, {"label": "大幅修改", "rate": 0.6},
    {"label": "小幅調整", "rate": 0.3}, {"label": "直接沿用", "rate": 0.1}]}


def weighted_item():
    counts = {"全新製作": 2600, "大幅修改": 1300, "小幅調整": 700, "直接沿用": 400}
    return billing.new_item("插畫", "張", 1.2, 0, billing.WEIGHTED,
                            billing.weighting_from_profile(PROFILE, counts))


def test_v2_item_is_simple_and_unchanged_in_value():
    item = billing.normalize_item({"name": "插畫", "unit_price": 1.2, "quantity": 5000.0})
    assert item["billing"] == billing.SIMPLE
    assert item["billable_quantity"] is None
    assert billing.item_subtotal(item) == 6000.0


def test_manual_billable_quantity_is_used_for_price():
    item = billing.new_item("插畫", "張", 1.2, 5000, billing.MANUAL)
    assert item["billable_quantity"] == 5000  # 沒填時等於委託數量
    item["billable_quantity"] = 3820
    assert billing.item_subtotal(item) == pytest.approx(4584.0)


def test_weighted_item_computes_both_quantities():
    item = weighted_item()
    assert item["quantity"] == 5000
    assert item["billable_quantity"] == 3630
    assert billing.item_subtotal(item) == pytest.approx(4356.0)


def test_weighted_rounding_can_be_turned_off():
    weighting = billing.weighting_from_profile({**PROFILE, "round_to_integer": False}, {"直接沿用": 5})
    assert billing.weighted_quantity(weighting) == 0.5
    weighting["round_to_integer"] = True
    assert billing.weighted_quantity(weighting) == 1.0


def test_weighted_without_details_falls_back_to_manual():
    item = billing.normalize_item({"name": "x", "unit_price": 1, "quantity": 10, "billing": "weighted"})
    assert item["billing"] == billing.MANUAL
    assert billing.effective_quantity(item) == 10


def test_unknown_billing_mode_and_bad_numbers_are_cleaned():
    item = billing.normalize_item({"name": "x", "unit_price": "abc", "quantity": None, "billing": "??"})
    assert (item["billing"], item["unit_price"], item["quantity"]) == (billing.SIMPLE, 0.0, 1.0)


def test_weighting_is_a_snapshot_of_the_profile():
    profile = copy.deepcopy(PROFILE)
    item = billing.new_item("插畫", "張", 1.2, 0, billing.WEIGHTED,
                            billing.weighting_from_profile(profile, {"全新製作": 1000}))
    profile["bands"][0]["rate"] = 0.5  # 之後修改加權表
    assert billing.item_subtotal(item) == pytest.approx(1200.0)


def test_switching_profile_keeps_counts_by_label():
    other = {"id": "p2", "name": "另一個", "bands": [{"label": "全新製作", "rate": 1.0}, {"label": "其他", "rate": 0.5}]}
    counts = {b["label"]: b["count"] for b in weighted_item()["weighting"]["bands"]}
    switched = billing.weighting_from_profile(other, counts)
    assert [b["count"] for b in switched["bands"]] == [2600, 0]


def test_items_total_and_quantity_summary():
    items = [weighted_item(), billing.new_item("急件加價", "件", 500, 1)]
    assert billing.items_total(items) == pytest.approx(4856.0)
    summary = {q["unit"]: q for q in billing.quantity_summary(items)}
    assert summary["張"]["quantity"] == 5000 and summary["張"]["billable"] == 3630
    assert summary["件"]["billable"] == 1


def test_unknown_item_fields_are_preserved():
    item = billing.normalize_item({"name": "x", "unit_price": 1, "quantity": 2, "note": "keep"})
    assert item["note"] == "keep"


def test_client_rates_override_general_ones_by_name():
    general = [billing.new_rate("插畫", "張", 1.0), billing.new_rate("上色", "張", 0.3)]
    client = {"rates": [billing.new_rate("插畫", "張", 1.2, billing.WEIGHTED)]}
    rates = billing.rates_for_client(client, general)
    assert [(r["name"], r["unit_price"]) for r in rates] == [("插畫", 1.2), ("上色", 0.3)]


def test_item_from_weighted_rate_uses_profile_or_falls_back():
    rate = billing.new_rate("插畫", "張", 1.2, billing.WEIGHTED)
    item = billing.item_from_rate(rate, PROFILE)
    assert item["billing"] == billing.WEIGHTED
    assert [b["label"] for b in item["weighting"]["bands"]] == ["全新製作", "大幅修改", "小幅調整", "直接沿用"]
    assert billing.item_from_rate(rate, None)["billing"] == billing.MANUAL


@pytest.mark.parametrize("value,text", [(5000, "5,000"), (1.25, "1.25"), (0.1, "0.1"), (3630.0, "3,630")])
def test_format_number(value, text):
    assert billing.format_number(value) == text


def test_describe_item():
    assert billing.describe_item(weighted_item()) == "插畫（單價 1.2，委託 5,000張 → 計費 3,630張，加權，小計 4,356）"
