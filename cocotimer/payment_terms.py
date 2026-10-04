"""結算日與收款日的計算規則。

規則（rule）長這樣，存在客戶資料或通用設定裡::

    {
        "settlement_months": 0,         # 結算在交件當月（0）、次月（1）、第 2 個月（2）…
        "settlement_day": 0,            # 每月幾號結算，0 = 月底
        "settlement_weekend": "none",   # 結算日遇假日：none / previous（提前到前一個工作日）/ next（順延到下一個工作日）
        "payment_type": "month_day",    # month_day：結算後第 N 個月的某日；days_after：結算後 N 天
        "payment_months": 1,            # month_day 用：0 = 同月、1 = 次月…
        "payment_day": 1,               # month_day 用：幾號付款，0 = 月底
        "payment_days": 60,             # days_after 用
        "payment_weekend": "none",      # 收款日遇假日
        "calendar_ids": ["..."],        # 判斷假日用的行事曆（見 holidays）；沒選就只看週六、週日
    }

預設：當月月底結算，次月 1 日收款。結算日以任務的交件日來算：交件日在結算日（含）之前就
當月結算，之後就下個月結算；settlement_months 再往後延幾個月（例如「交件次月月底結算」）。假日依選用的行事曆判斷（含補假、補班日），沒有選行事曆時只看週六、週日。
"""
import calendar
from datetime import date, datetime, timedelta
from typing import Callable, Optional, Tuple

MONTH_DAY, DAYS_AFTER = "month_day", "days_after"
WEEKEND_NONE, WEEKEND_PREVIOUS, WEEKEND_NEXT = "none", "previous", "next"
WEEKEND_OPTIONS = [(WEEKEND_NONE, "不調整"), (WEEKEND_PREVIOUS, "提前到前一個工作日"),
                   (WEEKEND_NEXT, "順延到下一個工作日")]

IsOff = Callable[[date], bool]


def weekends_only(d: date) -> bool:
    return d.weekday() >= 5

SETTLEMENT_MONTHS = [(0, "交件當月"), (1, "交件次月"), (2, "交件後第 2 個月"), (3, "交件後第 3 個月")]

DEFAULT_RULE = {
    "settlement_months": 0,
    "settlement_day": 0,
    "settlement_weekend": WEEKEND_NONE,
    "payment_type": MONTH_DAY,
    "payment_months": 1,
    "payment_day": 1,
    "payment_days": 60,
    "payment_weekend": WEEKEND_NONE,
    "calendar_ids": [],
}


def _int(value, default, low, high):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(value, low), high)


def normalize_rule(rule: Optional[dict]) -> dict:
    rule = rule if isinstance(rule, dict) else {}
    weekend = {k for k, _ in WEEKEND_OPTIONS}
    return {
        **rule,
        "settlement_months": _int(rule.get("settlement_months"), 0, 0, 12),
        "settlement_day": _int(rule.get("settlement_day"), 0, 0, 31),
        "settlement_weekend": rule.get("settlement_weekend") if rule.get("settlement_weekend") in weekend else WEEKEND_NONE,
        "payment_type": rule.get("payment_type") if rule.get("payment_type") in (MONTH_DAY, DAYS_AFTER) else MONTH_DAY,
        "payment_months": _int(rule.get("payment_months"), 1, 0, 24),
        "payment_day": _int(rule.get("payment_day"), 1, 0, 31),
        "payment_days": _int(rule.get("payment_days"), 60, 0, 730),
        "payment_weekend": rule.get("payment_weekend") if rule.get("payment_weekend") in weekend else WEEKEND_NONE,
        "calendar_ids": [c for c in rule.get("calendar_ids", []) if isinstance(c, str)]
        if isinstance(rule.get("calendar_ids"), list) else [],
    }


def _add_months(year: int, month: int, months: int) -> Tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def _day_in_month(year: int, month: int, day: int) -> date:
    """day = 0 表示月底；超過當月天數也取月底（例如 2 月 31 日 → 2 月最後一天）。"""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, last if day == 0 else min(day, last))


def adjust_weekend(d: date, mode: str, is_off: IsOff = weekends_only) -> date:
    """遇到休息日時往前或往後移到工作日（最多移 30 天，避免行事曆資料有誤時卡住）。"""
    step = {WEEKEND_PREVIOUS: -1, WEEKEND_NEXT: 1}.get(mode)
    if step is None:
        return d
    moved = d
    for _ in range(30):
        if not is_off(moved):
            return moved
        moved += timedelta(days=step)
    return d


def settlement_date(base: date, rule: dict, is_off: IsOff = weekends_only) -> date:
    rule = normalize_rule(rule)
    cutoff = _day_in_month(base.year, base.month, rule["settlement_day"])
    year, month = base.year, base.month
    if base > cutoff:
        year, month = _add_months(year, month, 1)
    year, month = _add_months(year, month, rule["settlement_months"])
    settled = _day_in_month(year, month, rule["settlement_day"])
    return adjust_weekend(settled, rule["settlement_weekend"], is_off)


def payment_date(settled: date, rule: dict, is_off: IsOff = weekends_only) -> date:
    rule = normalize_rule(rule)
    if rule["payment_type"] == DAYS_AFTER:
        paid = settled + timedelta(days=rule["payment_days"])
    else:
        year, month = _add_months(settled.year, settled.month, rule["payment_months"])
        paid = _day_in_month(year, month, rule["payment_day"])
        if paid < settled:  # 例如「同月 1 日」但已經過了，就順延一個月
            year, month = _add_months(year, month, 1)
            paid = _day_in_month(year, month, rule["payment_day"])
    return adjust_weekend(paid, rule["payment_weekend"], is_off)


def compute_dates(base: str, rule: Optional[dict], is_off: Optional[IsOff] = None) -> Tuple[str, str]:
    """由交件日（YYYY-MM-DD）算出（結算日, 收款日）；日期格式不對時回傳兩個空字串。"""
    try:
        base_date = datetime.strptime(base, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return "", ""
    is_off = is_off or weekends_only
    settled = settlement_date(base_date, rule, is_off)
    return settled.isoformat(), payment_date(settled, rule, is_off).isoformat()


def describe_rule(rule: Optional[dict]) -> str:
    rule = normalize_rule(rule)
    weekend = dict(WEEKEND_OPTIONS)
    day = lambda d: "月底" if d == 0 else f" {d} 日"
    later = rule["settlement_months"]
    if later:
        prefix = {1: "交件次月"}.get(later, f"交件後第 {later} 個月")
        text = f"{prefix}{day(rule['settlement_day'])}結算"
    else:
        text = f"每月{day(rule['settlement_day'])}結算"
    if rule["settlement_weekend"] != WEEKEND_NONE:
        text += f"（遇假日{weekend[rule['settlement_weekend']]}）"
    if rule["payment_type"] == DAYS_AFTER:
        text += f"，結算後 {rule['payment_days']} 天收款"
    else:
        months = {0: "當月", 1: "次月", 2: "次次月"}.get(rule["payment_months"], f"{rule['payment_months']} 個月後")
        text += f"，{'結算' if later else ''}{months}{day(rule['payment_day'])}收款"
    if rule["payment_weekend"] != WEEKEND_NONE:
        text += f"（遇假日{weekend[rule['payment_weekend']]}）"
    return text
