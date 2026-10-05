"""統計頁用的計算（不依賴 Qt，方便測試）。

日期一律是 YYYY-MM-DD 字串，期間用 (start, end) 表示，兩端都包含在內。
金額不換匯：不同幣別分開加總，回傳 {"NTD": 1200.0, "USD": 30.0} 這樣的 dict。
"""
import calendar
import csv
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from . import billing
from . import tasks as tasks_service
from .models import TaskItem

Amounts = Dict[str, float]


# --- 期間 ---

def period(kind: str, year: int, month: int) -> Tuple[str, str]:
    """kind 是 "month" 或 "year"。"""
    if kind == "year":
        return f"{year:04d}-01-01", f"{year:04d}-12-31"
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def data_span(tasks: Iterable[TaskItem], records: dict, today: Optional[date] = None) -> Tuple[str, str]:
    """「全部」要看的期間：最早有資料的那個月的 1 日，到今天（或更晚的最後一筆資料）。"""
    today = (today or date.today()).isoformat()
    days = [d for t in tasks for d in (t.due_date, t.delivered_date, t.paid_date) if isinstance(d, str) and len(d) >= 10]
    days += [d for d in records if isinstance(d, str) and len(d) >= 10]
    days = [d[:10] for d in days if d[:4].isdigit()]
    first = min(days, default=today)
    return first[:7] + "-01", max(max(days, default=today), today)


def month_keys(start: str, end: str) -> List[str]:
    """start 到 end 之間的每個月："2025-03"、"2025-04"…"""
    y, m = int(start[:4]), int(start[5:7])
    last = (int(end[:4]), int(end[5:7]))
    keys = []
    while (y, m) <= last:
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return keys


def year_keys(start: str, end: str) -> List[str]:
    return [f"{y:04d}" for y in range(int(start[:4]), int(end[:4]) + 1)]


def in_range(day: str, start: str, end: str) -> bool:
    return isinstance(day, str) and len(day) >= 10 and start <= day[:10] <= end


def _add(bucket: Amounts, currency: str, amount: float) -> None:
    if amount:
        bucket[currency or "NTD"] = bucket.get(currency or "NTD", 0.0) + amount


def primary_currency(*amounts: Amounts) -> str:
    """金額最多的幣別（同樣多時台幣優先）；沒有任何金額時是 NTD。"""
    totals: Amounts = {}
    for a in amounts:
        for cur, v in a.items():
            totals[cur] = totals.get(cur, 0.0) + v
    if not totals:
        return "NTD"
    return max(totals, key=lambda c: (totals[c], c in ("NTD", "TWD")))


# --- 收入 ---

def income(tasks: Iterable[TaskItem], start: str, end: str) -> Amounts:
    """期間內實際收到的款項（依收款日）。"""
    result: Amounts = {}
    for t in tasks:
        if t.status == tasks_service.PAID and in_range(t.paid_date, start, end):
            _add(result, t.currency, t.get_total_price())
    return result


def expected(tasks: Iterable[TaskItem], start: str, end: str) -> Amounts:
    """還沒收款、預計收款日落在期間內的金額。"""
    result: Amounts = {}
    for t in tasks:
        if t.status in (tasks_service.DELIVERED, tasks_service.INVOICED) and in_range(t.payment_date, start, end):
            _add(result, t.currency, t.get_total_price())
    return result


def receivable(tasks: Iterable[TaskItem], today: Optional[date] = None) -> Tuple[Amounts, Amounts]:
    """目前所有待收款（已交付、已請款），以及其中已經超過預計收款日的部分。"""
    today = (today or date.today()).isoformat()
    total: Amounts = {}
    late: Amounts = {}
    for t in tasks:
        if t.status in (tasks_service.DELIVERED, tasks_service.INVOICED):
            amount = t.get_total_price()
            _add(total, t.currency, amount)
            if t.payment_date and t.payment_date < today:
                _add(late, t.currency, amount)
    return total, late


def income_by_month(tasks: Iterable[TaskItem], year: int, currency: str) -> List[float]:
    """某一年每個月收到的款項（只算指定幣別），長度 12。"""
    months = [0.0] * 12
    prefix = f"{year:04d}-"
    for t in tasks:
        if (t.status == tasks_service.PAID and (t.currency or "NTD") == currency
                and isinstance(t.paid_date, str) and t.paid_date.startswith(prefix)):
            try:
                months[int(t.paid_date[5:7]) - 1] += t.get_total_price()
            except ValueError:
                continue
    return months


def income_by_key(tasks: Iterable[TaskItem], keys: List[str], currency: str) -> List[float]:
    """依收款日的年（"2025"）或年月（"2025-03"）加總，順序跟 keys 一樣；只算指定幣別。"""
    values = dict.fromkeys(keys, 0.0)
    size = len(keys[0]) if keys else 0
    for t in tasks:
        if t.status == tasks_service.PAID and (t.currency or "NTD") == currency and isinstance(t.paid_date, str):
            key = t.paid_date[:size]
            if key in values:
                values[key] += t.get_total_price()
    return [values[k] for k in keys]


def currencies_used(tasks: Iterable[TaskItem]) -> List[str]:
    found = {t.currency or "NTD" for t in tasks if t.get_total_price()}
    return sorted(found, key=lambda c: (c not in ("NTD", "TWD"), c)) or ["NTD"]


# --- 任務 ---

def period_tasks(tasks: Iterable[TaskItem], start: str, end: str) -> List[TaskItem]:
    """這段期間「有動靜」的任務：交件日、交付日或收款日落在期間內。依交件日排序。"""
    found = [t for t in tasks if any(in_range(d, start, end) for d in (t.due_date, t.delivered_date, t.paid_date))]
    return sorted(found, key=lambda t: f"{t.due_date} {t.due_time}")


def delivered_count(tasks: Iterable[TaskItem], start: str, end: str) -> int:
    return sum(1 for t in tasks if t.status != tasks_service.IN_PROGRESS and in_range(t.delivered_date, start, end))


def focus_total(tasks: Iterable[TaskItem], start: str, end: str) -> int:
    return sum(tasks_service.focus_seconds(t, start, end) for t in tasks)


def client_rows(tasks: Iterable[TaskItem], start: str, end: str) -> List[dict]:
    """依客戶整理期間內的收款、交付件數與專注時間；收款最多的排前面。"""
    rows: Dict[str, dict] = {}
    for t in tasks:
        name = (t.client or "").strip() or "（沒有指定客戶）"
        paid = t.status == tasks_service.PAID and in_range(t.paid_date, start, end)
        delivered = t.status != tasks_service.IN_PROGRESS and in_range(t.delivered_date, start, end)
        focus = tasks_service.focus_seconds(t, start, end)
        if not (paid or delivered or focus):
            continue
        row = rows.setdefault(name, {"name": name, "paid": {}, "delivered": 0, "focus": 0})
        if paid:
            _add(row["paid"], t.currency, t.get_total_price())
        row["delivered"] += int(delivered)
        row["focus"] += focus
    main = primary_currency(*(r["paid"] for r in rows.values()))
    return sorted(rows.values(), key=lambda r: (-r["paid"].get(main, 0.0), -sum(r["paid"].values()), -r["delivered"], r["name"]))


# --- 工時 ---

def _session_seconds(session: dict, now: datetime) -> float:
    try:
        start = datetime.fromisoformat(session["start"])
        end = datetime.fromisoformat(session["end"]) if session.get("end") else now
    except (KeyError, TypeError, ValueError):
        return 0.0
    return max(0.0, (end - start).total_seconds())


def day_work_seconds(record, now: Optional[datetime] = None) -> float:
    now = now or datetime.now()
    return sum(_session_seconds(s, now) for s in getattr(record, "sessions", []) if isinstance(s, dict))


def work_by_day(records: dict, start: str, end: str, now: Optional[datetime] = None) -> List[Tuple[str, float]]:
    """期間內每一天的工時（秒），沒打卡的日子是 0。"""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    result = []
    for n in range((e - s).days + 1):
        d = date.fromordinal(s.toordinal() + n).isoformat()
        result.append((d, day_work_seconds(records[d], now) if d in records else 0.0))
    return result


def work_by_month(records: dict, year: int, now: Optional[datetime] = None) -> List[float]:
    months = [0.0] * 12
    prefix = f"{year:04d}-"
    for d, record in records.items():
        if isinstance(d, str) and d.startswith(prefix):
            try:
                months[int(d[5:7]) - 1] += day_work_seconds(record, now)
            except ValueError:
                continue
    return months


def work_by_key(records: dict, keys: List[str], now: Optional[datetime] = None) -> List[float]:
    values = dict.fromkeys(keys, 0.0)
    size = len(keys[0]) if keys else 0
    for d, record in records.items():
        if isinstance(d, str) and d[:size] in values:
            values[d[:size]] += day_work_seconds(record, now)
    return [values[k] for k in keys]


# --- 匯出 ---

TASK_HEADERS = ["建立日期", "專案", "任務", "客戶", "狀態", "交件日", "交件時間", "交付日", "結算日", "預計收款日",
                "請款日", "收款日", "幣別", "金額", "數量（委託 → 計費）", "價格項目", "番茄鐘專注（小時）", "時薪",
                "完成度", "備註"]
WORK_HEADERS = ["日期", "開始", "結束", "時長（分鐘）"]
EVENT_HEADERS = ["日期", "時間", "標題", "描述", "已完成"]


def _quantity_text(task: TaskItem) -> str:
    parts = []
    for q in billing.quantity_summary(task.price_items):
        qty, billable = billing.format_number(q["quantity"]), billing.format_number(q["billable"])
        parts.append(f"{qty}{q['unit']}" if qty == billable else f"{qty}{q['unit']} → {billable}{q['unit']}")
    return "、".join(parts)


def task_export_row(t: TaskItem) -> list:
    rate = tasks_service.hourly_rate(t)
    return [t.created_date, t.project_name, t.title, t.client, tasks_service.status_text(t), t.due_date, t.due_time,
            t.delivered_date, t.settlement_date, t.payment_date, t.invoiced_date, t.paid_date, t.currency or "NTD",
            round(t.get_total_price(), 2), _quantity_text(t),
            "; ".join(billing.describe_item(i) for i in t.price_items),
            round(tasks_service.focus_seconds(t) / 3600, 2), round(rate) if rate else "", f"{t.completion}%",
            t.description]


def export_tables(tasks, events, records, start: str = "", end: str = "") -> Dict[str, Tuple[list, list]]:
    """要匯出的表格：{"任務": (標題列, 資料列), "工時": ..., "行程": ..., "總計": ...}。start、end 空白表示全部。"""
    tasks = list(tasks)
    everything = not (start and end)
    task_list = tasks if everything else period_tasks(tasks, start, end)
    task_rows = [task_export_row(t) for t in sorted(task_list, key=lambda t: f"{t.due_date} {t.due_time}")]

    work_rows = []
    for d in sorted(records):
        if not everything and not in_range(d, start, end):
            continue
        for s in getattr(records[d], "sessions", []):
            if not isinstance(s, dict):
                continue
            seconds = _session_seconds(s, datetime.now()) if s.get("end") else None
            work_rows.append([d, s.get("start", ""), s.get("end") or "", round(seconds / 60, 1) if seconds else ""])

    event_rows = [[e.date, e.time, e.title, e.description, "是" if e.completed else "否"]
                  for e in sorted(events, key=lambda e: (e.date, e.time)) if everything or in_range(e.date, start, end)]

    lo, hi = (start, end) if not everything else ("0000-01-01", "9999-12-31")
    all_tasks = list(tasks)
    paid, due = income(all_tasks, lo, hi), expected(all_tasks, lo, hi)  # 和統計頁的數字一致
    summary_rows = [[cur, round(paid.get(cur, 0.0), 2), round(due.get(cur, 0.0), 2)]
                    for cur in sorted(set(paid) | set(due))]
    summary_rows.append(["工時（小時）", round(sum(v for _d, v in work_by_day(records, lo, hi)) / 3600, 2)
                         if not everything else round(sum(day_work_seconds(r) for r in records.values()) / 3600, 2), ""])
    summary_rows.append(["番茄鐘專注（小時）", round(focus_total(all_tasks, lo, hi) / 3600, 2), ""])
    return {"總計": (["項目／幣別", "已收款", "預計收款"], summary_rows),
            "任務": (TASK_HEADERS, task_rows), "工時": (WORK_HEADERS, work_rows), "行程": (EVENT_HEADERS, event_rows)}


def write_csv_files(base_path: str, tables: Dict[str, Tuple[list, list]]) -> List[str]:
    """每個表格各存一個 CSV（Excel 打得開，UTF-8 含 BOM）：「檔名_任務.csv」等。回傳寫出的檔案。"""
    stem = base_path[:-4] if base_path.lower().endswith(".csv") else base_path
    written = []
    for name, (headers, rows) in tables.items():
        path = f"{stem}_{name}.csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        written.append(path)
    return written


def write_xlsx(path: str, tables: Dict[str, Tuple[list, list]]) -> None:
    from openpyxl import Workbook  # 選用套件；沒有安裝時由呼叫端改存 CSV
    wb = Workbook()
    wb.remove(wb.active)
    for name, (headers, rows) in tables.items():
        ws = wb.create_sheet(name)
        ws.append(headers)
        for row in rows:
            ws.append(row)
    wb.save(path)
