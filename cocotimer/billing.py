"""計費計算。只處理資料，不碰介面，方便測試。

一個價格項目（任務的 ``price_items`` 裡的一筆）長這樣::

    {
        "name": "插畫",
        "unit": "張",
        "unit_price": 3000,
        "quantity": 10,              # 委託數量
        "billing": "weighted",       # simple / manual / weighted
        "billable_quantity": 7,      # 計費數量（simple 時為 None）
        "weighting": {               # 只有 weighted 才有；是加權表當下的副本
            "profile_id": "...", "profile_name": "常用加權",
            "round_to_integer": true,
            "bands": [{"label": "全新製作", "rate": 1.0, "count": 5}, ...]
        }
    }

- simple：小計 = 單價 × 委託數量
- manual：小計 = 單價 × 計費數量（沒填就等於委託數量）
- weighted：委託數量 = 各級距數量加總，計費數量 = Σ 數量 × 比例

加權明細存的是副本，之後修改加權表不會改到已經存在的任務金額。
"""
import copy
import uuid
from typing import Dict, Iterable, List, Optional

SIMPLE, MANUAL, WEIGHTED = "simple", "manual", "weighted"
BILLING_MODES = [(SIMPLE, "簡單"), (MANUAL, "委託與計費分開"), (WEIGHTED, "加權計算")]
BILLING_LABELS = dict(BILLING_MODES)

UNITS = ["件", "張", "頁", "字", "小時", "分鐘", "次", "式"]


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --- 加權 ---

def default_weighting_profile() -> dict:
    return {
        "id": new_id(),
        "name": "常用加權（範例，請依合約調整）",
        "round_to_integer": True,
        "bands": [
            {"label": "全新製作", "rate": 1.0},
            {"label": "大幅修改", "rate": 0.6},
            {"label": "小幅調整", "rate": 0.3},
            {"label": "直接沿用", "rate": 0.1},
        ],
    }


def weighting_from_profile(profile: dict, counts: Optional[Dict[str, float]] = None) -> dict:
    """依加權表建立一份加權明細；``counts`` 用級距名稱帶入原本的數量。"""
    counts = counts or {}
    return {
        "profile_id": profile.get("id", ""),
        "profile_name": profile.get("name", ""),
        "round_to_integer": bool(profile.get("round_to_integer", True)),
        "bands": [{"label": b.get("label", ""), "rate": _num(b.get("rate"), 1.0),
                   "count": _num(counts.get(b.get("label", "")), 0.0)}
                  for b in profile.get("bands", [])],
    }


def weighted_source_quantity(weighting: dict) -> float:
    return sum(_num(b.get("count")) for b in weighting.get("bands", []))


def weighted_quantity(weighting: dict) -> float:
    total = sum(_num(b.get("count")) * _num(b.get("rate"), 1.0) for b in weighting.get("bands", []))
    if weighting.get("round_to_integer", True):
        return float(int(total + 0.5))
    return round(total, 2)


# --- 價格項目 ---

def new_item(name="", unit="", unit_price=0.0, quantity=1.0, billing=SIMPLE, weighting=None) -> dict:
    return normalize_item({"name": name, "unit": unit, "unit_price": unit_price, "quantity": quantity,
                           "billing": billing, "billable_quantity": None, "weighting": weighting})


def normalize_item(item: dict) -> dict:
    """補齊欄位並依計費方式重新計算委託／計費數量。會保留不認識的欄位。"""
    item = dict(item)
    item.setdefault("name", "")
    item["unit"] = item.get("unit") or ""
    item["unit_price"] = _num(item.get("unit_price"))
    item["quantity"] = _num(item.get("quantity"), 1.0)
    billing = item.get("billing")
    if billing not in BILLING_LABELS:
        billing = SIMPLE
    item["billing"] = billing

    if billing == WEIGHTED and isinstance(item.get("weighting"), dict):
        item["quantity"] = weighted_source_quantity(item["weighting"])
        item["billable_quantity"] = weighted_quantity(item["weighting"])
    elif billing == WEIGHTED:
        item["billing"] = MANUAL
        billing = MANUAL
    if billing == MANUAL:
        bq = item.get("billable_quantity")
        item["billable_quantity"] = item["quantity"] if bq is None else _num(bq, item["quantity"])
        item["weighting"] = None
    elif billing == SIMPLE:
        item["billable_quantity"] = None
        item["weighting"] = None
    return item


def effective_quantity(item: dict) -> float:
    """實際拿來計價的數量。"""
    billing = item.get("billing", SIMPLE)
    if billing == WEIGHTED and isinstance(item.get("weighting"), dict):
        return weighted_quantity(item["weighting"])
    if billing in (MANUAL, WEIGHTED) and item.get("billable_quantity") is not None:
        return _num(item["billable_quantity"])
    return _num(item.get("quantity"))


def item_subtotal(item: dict) -> float:
    return round(_num(item.get("unit_price")) * effective_quantity(item), 2)


def items_total(items: Iterable[dict]) -> float:
    return round(sum(item_subtotal(i) for i in items), 2)


def quantity_summary(items: Iterable[dict]) -> List[dict]:
    """依單位加總委託與計費數量，例如 [{"unit": "張", "quantity": 10, "billable": 7}]。"""
    by_unit: Dict[str, dict] = {}
    for item in items:
        row = by_unit.setdefault(item.get("unit") or "", {"unit": item.get("unit") or "", "quantity": 0.0, "billable": 0.0})
        row["quantity"] += _num(item.get("quantity"))
        row["billable"] += effective_quantity(item)
    return list(by_unit.values())


def format_number(value: float) -> str:
    """5000.0 → 5,000；1.25 → 1.25"""
    value = round(_num(value), 2)
    return f"{value:,.0f}" if value == int(value) else f"{value:,.2f}".rstrip("0").rstrip(".")


def describe_item(item: dict) -> str:
    """CSV／提示用的一行描述。"""
    unit = item.get("unit") or ""
    text = f"{item.get('name', '')}（單價 {format_number(item.get('unit_price'))}"
    if item.get("billing", SIMPLE) == SIMPLE:
        text += f" × {format_number(item.get('quantity'))}{unit}"
    else:
        text += (f"，委託 {format_number(item.get('quantity'))}{unit}"
                 f" → 計費 {format_number(effective_quantity(item))}{unit}")
        if item.get("billing") == WEIGHTED:
            text += "，加權"
    return text + f"，小計 {format_number(item_subtotal(item))}）"


# --- 單價範本 ---

def new_rate(name="", unit="", unit_price=0.0, billing=SIMPLE) -> dict:
    return {"id": new_id(), "name": name, "unit": unit, "unit_price": _num(unit_price), "billing": billing}


def rates_for_client(client: Optional[dict], general_rates: List[dict]) -> List[dict]:
    """客戶自己的範本優先；同名的通用範本會被客戶的蓋過。"""
    own = list(client.get("rates", [])) if client else []
    names = {r.get("name") for r in own}
    return own + [r for r in general_rates if r.get("name") not in names]


def item_from_rate(rate: dict, profile: Optional[dict]) -> dict:
    billing = rate.get("billing", SIMPLE)
    weighting = None
    if billing == WEIGHTED:
        if profile:
            weighting = weighting_from_profile(profile)
        else:
            billing = MANUAL
    quantity = 0.0 if billing == WEIGHTED else 1.0
    return new_item(rate.get("name", ""), rate.get("unit", ""), rate.get("unit_price", 0.0),
                    quantity, billing, copy.deepcopy(weighting))


def find_profile(profiles: List[dict], profile_id: str) -> Optional[dict]:
    for p in profiles:
        if p.get("id") == profile_id:
            return p
    return None
