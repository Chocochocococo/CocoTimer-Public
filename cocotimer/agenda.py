"""行事曆用的資料整理：某一天有哪些行程、交件、假日（不依賴 Qt，方便測試）。

每個項目是一個 dict：
    {"kind": "event" | "due" | "overdue" | "done", "time": "10:00", "title": "...",
     "detail": "...", "ref": 行程或任務物件}
"""
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

from . import tasks as tasks_service
from .holidays import make_is_off

KIND_LABELS = {"event": "行程", "due": "任務交件", "overdue": "逾期未交", "done": "已完成"}


def day_items(day: date, events: Iterable, tasks: Iterable, now: Optional[datetime] = None) -> List[dict]:
    key = day.isoformat()
    now = now or datetime.now()
    items = []
    for e in events:
        if e.date == key:
            items.append({"kind": "done" if e.completed else "event", "time": e.time, "title": e.title,
                          "detail": e.description, "ref": e})
    for t in tasks:
        if t.due_date != key:
            continue
        if t.status != tasks_service.IN_PROGRESS:
            kind, detail = "done", tasks_service.status_text(t)
        else:
            note, due_kind = tasks_service.due_info(t, now)
            kind, detail = ("overdue" if due_kind == "overdue" else "due"), note
        meta = " · ".join(p for p in (t.client, detail) if p)
        items.append({"kind": kind, "time": t.due_time, "title": t.title, "detail": meta, "ref": t})
    order = {"overdue": 0, "due": 1, "event": 2, "done": 3}
    return sorted(items, key=lambda i: (i["time"] or "99:99", order[i["kind"]]))


def month_items(year: int, month: int, events: Iterable, tasks: Iterable,
                now: Optional[datetime] = None, padding: bool = True) -> Dict[str, List[dict]]:
    """一個月（含月曆前後補的日子）每天的項目：{"2026-10-03": [...]}，沒有項目的日子不列。"""
    events, tasks = list(events), list(tasks)
    result = {}
    for day in month_days(year, month, padding):
        items = day_items(day, events, tasks, now)
        if items:
            result[day.isoformat()] = items
    return result


def month_days(year: int, month: int, padding: bool = True, sunday_first: bool = True) -> List[date]:
    """月曆格子要顯示的日期（週日開頭，補滿整週；padding=False 只回傳當月）。"""
    first = date(year, month, 1)
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
    if not padding:
        return [first + timedelta(days=i) for i in range((last - first).days + 1)]
    offset = (first.weekday() + 1) % 7 if sunday_first else first.weekday()
    start = first - timedelta(days=offset)
    days = (last - start).days + 1
    total = days + (-days % 7)
    return [start + timedelta(days=i) for i in range(total)]


def holiday_names(calendars: List[dict], calendar_ids: Iterable[str], days: Iterable[date]) -> Dict[str, dict]:
    """選用行事曆中有名稱的日子：{"2026-10-10": {"name": "國慶日", "off": True}}。"""
    wanted = set(calendar_ids or [])
    result = {}
    for d in days:
        key = d.isoformat()
        for c in calendars:
            if c.get("id") in wanted and key in c.get("days", {}):
                entry = c["days"][key]
                if key not in result or entry.get("off"):
                    result[key] = entry
    return result


def off_days(calendars: List[dict], calendar_ids: Iterable[str], days: Iterable[date]) -> set:
    is_off = make_is_off(calendars, calendar_ids)
    return {d.isoformat() for d in days if is_off(d)}
