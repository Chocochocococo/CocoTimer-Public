"""幣別：統一寫法，以及用使用者自己填的匯率換算成常用幣別（不連網，也不會自動更新匯率）。

匯率表的格式：{"base": "NTD", "rates": {"USD": 32.0, "JPY": 0.21}}，意思是 1 USD = 32 NTD。
常用幣別改了也不用重填：換算時會經過原本的 base 交叉換算。
"""
from typing import Dict, List, Optional, Tuple

ALIASES = {"TWD": "NTD", "NT": "NTD", "NT$": "NTD", "台幣": "NTD", "臺幣": "NTD", "新台幣": "NTD", "新臺幣": "NTD",
           "RMB": "CNY", "人民幣": "CNY", "日幣": "JPY", "日圓": "JPY", "日元": "JPY", "美金": "USD", "美元": "USD",
           "歐元": "EUR", "港幣": "HKD", "英鎊": "GBP"}


def normalize(code) -> str:
    """"twd"、"台幣"、"NT$" → "NTD"；空白 → "NTD"；其他轉成大寫。"""
    text = str(code or "").strip()
    upper = text.upper()
    return ALIASES.get(upper) or ALIASES.get(text) or upper or "NTD"


def _table(table) -> Tuple[str, Dict[str, float]]:
    if not isinstance(table, dict):
        return "NTD", {}
    rates = {}
    for cur, value in (table.get("rates") or {}).items():
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            rates[normalize(cur)] = value
    return normalize(table.get("base")), rates


def rate(currency: str, target: str, table) -> Optional[float]:
    """1 單位的 currency 等於多少 target；不知道時回傳 None。"""
    currency, target = normalize(currency), normalize(target)
    if currency == target:
        return 1.0
    base, rates = _table(table)
    in_base = lambda c: 1.0 if c == base else rates.get(c)
    a, b = in_base(currency), in_base(target)
    return a / b if a and b else None


def convert(amounts: Dict[str, float], target: str, table) -> Tuple[float, List[str]]:
    """把好幾種幣別的金額換算成 target，回傳（換算後的合計, 沒有匯率而沒算進去的幣別）。"""
    total, missing = 0.0, []
    for cur, value in amounts.items():
        r = rate(cur, target, table)
        if r is None:
            missing.append(cur)
        else:
            total += value * r
    return total, sorted(missing)


def rebase(table, base: str) -> dict:
    """改成以 base 為準的匯率表（換算不出來的幣別會拿掉）。"""
    old_base, rates = _table(table)
    base = normalize(base)
    out = {}
    for cur in set(rates) | {old_base}:
        r = rate(cur, base, table) if cur != base else None
        if r:
            out[cur] = round(r, 6)
    return {"base": base, "rates": out}


def set_rate(table, base: str, currency: str, value: float) -> dict:
    """設定 1 currency = value base；value 是 0 表示清掉。"""
    new = rebase(table, base)
    currency = normalize(currency)
    if value and value > 0:
        new["rates"][currency] = value
    else:
        new["rates"].pop(currency, None)
    return new
