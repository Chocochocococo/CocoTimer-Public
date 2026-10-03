"""假日行事曆：匯入、合併與查詢。

一個行事曆長這樣（存在 holidays.json）::

    {"id": "...", "name": "台灣國定假日", "note": "資料來源…",
     "days": {"2026-10-09": {"name": "補假", "off": true},
              "2026-02-14": {"name": "補班", "off": false}}}

``off`` 為 false 的是補班日（週末但要上班）。沒有列在行事曆裡的日子，週六、週日視為休息。

可以匯入：
- 台灣「中華民國政府行政機關辦公日曆表」官方 CSV（Big5 或 UTF-8，「是否放假」2 = 放假、0 = 上班）
- iCalendar（.ics）：Google 日曆、Outlook 匯出的各國假日
- 簡單 CSV：日期, 名稱[, 類型]（類型寫「補班」或「上班」表示補班日）
- 整理成 JSON 的辦公日曆（[{"date": "20260101", "isHoliday": true, "description": "…"}]）
"""
import csv
import io
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from . import tw_holidays

Days = Dict[str, dict]

DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d")
WORKDAY_WORDS = {"補班", "上班", "工作日", "work", "workday", "0", "false"}
MAX_EVENT_DAYS = 60


def new_calendar(name: str, note: str = "") -> dict:
    return {"id": uuid.uuid4().hex[:12], "name": name, "note": note, "days": {}}


def taiwan_calendar() -> dict:
    calendar = new_calendar("台灣國定假日", f"內建 {tw_holidays.YEARS[0]}–{tw_holidays.YEARS[-1]} 年資料，"
                                         f"來源：{tw_holidays.SOURCE}")
    calendar["days"] = {d: {"name": name, "off": off} for d, (name, off) in tw_holidays.DAYS.items()}
    return calendar


def parse_date(text: str) -> Optional[date]:
    text = (text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def _keep(days: Days, d: date, name: str, off: bool) -> None:
    """只留下「跟平常不一樣」或有名稱的日子：平日放假、週末補班、有名字的節日。"""
    if off != _is_weekend(d) or name:
        days[d.isoformat()] = {"name": name or ("放假" if off else "補班"), "off": off}


# --- 各種格式 ---

def parse_taiwan_rows(rows: List[List[str]]) -> Days:
    header = [h.strip() for h in rows[0]]
    find = lambda *keys: next((i for i, h in enumerate(header) if any(k in h for k in keys)), None)
    date_col, off_col, note_col = find("日期"), find("放假"), find("備註", "說明")
    if date_col is None or off_col is None:
        raise ValueError("找不到「日期」或「是否放假」欄位")
    days: Days = {}
    for row in rows[1:]:
        if len(row) <= max(date_col, off_col):
            continue
        d = parse_date(row[date_col])
        if d is None:
            continue
        name = row[note_col].strip() if note_col is not None and note_col < len(row) else ""
        _keep(days, d, name, row[off_col].strip() == "2")
    return days


def parse_simple_rows(rows: List[List[str]]) -> Days:
    days: Days = {}
    for row in rows:
        if not row:
            continue
        d = parse_date(row[0])
        if d is None:
            continue  # 表頭或空白列
        name = row[1].strip() if len(row) > 1 else ""
        kind = row[2].strip().lower() if len(row) > 2 else ""
        off = kind not in WORKDAY_WORDS
        days[d.isoformat()] = {"name": name or ("放假" if off else "補班"), "off": off}
    return days


def parse_ics(text: str) -> Days:
    lines: List[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]  # 折行
        else:
            lines.append(raw.strip())
    days: Days = {}
    event = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            event = {}
        elif line == "END:VEVENT" and event is not None:
            start = parse_date((event.get("DTSTART") or "")[:8])
            if start is not None:
                end = parse_date((event.get("DTEND") or "")[:8])
                span = (end - start).days if end and end > start else 1
                name = event.get("SUMMARY", "")
                for i in range(min(span, MAX_EVENT_DAYS)):
                    d = start + timedelta(days=i)
                    days[d.isoformat()] = {"name": name or "假日", "off": True}
            event = None
        elif event is not None and ":" in line:
            key, value = line.split(":", 1)
            key = key.split(";", 1)[0].upper()
            if key == "SUMMARY":
                value = re.sub(r"\\([,;\\nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)
            event[key] = value
    return days


def parse_json_records(records: Iterable[dict]) -> Days:
    days: Days = {}
    for r in records:
        d = parse_date(str(r.get("date", "")))
        if d is not None:
            _keep(days, d, (r.get("description") or "").strip(), bool(r.get("isHoliday")))
    return days


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp950", "big5hkscs"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("無法辨識檔案的文字編碼")


def parse_file(path: str) -> Tuple[Days, str]:
    """讀取假日檔案，回傳（日子, 辨識出的格式名稱）。"""
    with open(path, "rb") as f:
        text = _decode(f.read())
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ics" or text.lstrip().startswith("BEGIN:VCALENDAR"):
        return parse_ics(text), "iCalendar 行事曆"
    if ext == ".json":
        try:
            data = json.loads(text)
        except ValueError as e:
            raise ValueError("JSON 格式不正確") from e
        if not isinstance(data, list):
            raise ValueError("JSON 內容應該是日期清單")
        return parse_json_records(r for r in data if isinstance(r, dict)), "辦公日曆 JSON"
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    if not rows:
        raise ValueError("檔案是空的")
    if any("放假" in h for h in rows[0]):
        return parse_taiwan_rows(rows), "行政機關辦公日曆表"
    return parse_simple_rows(rows), "日期清單"


# --- 合併與查詢 ---

def merge(calendar: dict, days: Days) -> Tuple[int, int]:
    """把匯入的日子併進行事曆，回傳（新增幾天, 更新幾天）。"""
    existing = calendar.setdefault("days", {})
    added = sum(1 for d in days if d not in existing)
    updated = sum(1 for d, v in days.items() if d in existing and existing[d] != v)
    existing.update(days)
    return added, updated


def years(calendar: dict) -> List[int]:
    return sorted({int(d[:4]) for d in calendar.get("days", {})})


def make_is_off(calendars: List[dict], calendar_ids: Iterable[str]) -> Callable[[date], bool]:
    """回傳一個函式：某天是不是休息日。任一行事曆說放假就放假；說補班就上班；其他看是不是週末。"""
    wanted = set(calendar_ids or [])
    selected = [c for c in calendars if c.get("id") in wanted]

    def is_off(d: date) -> bool:
        key = d.isoformat()
        marks = [c["days"][key]["off"] for c in selected if key in c.get("days", {})]
        if any(marks):
            return True
        if marks:
            return False
        return _is_weekend(d)

    return is_off


def missing_years(calendars: List[dict], calendar_ids: Iterable[str], needed: Iterable[int]) -> Dict[str, List[int]]:
    """選用的行事曆中，哪些缺少需要年份的資料：{行事曆名稱: [年份…]}。"""
    wanted = set(calendar_ids or [])
    result = {}
    for c in calendars:
        if c.get("id") in wanted:
            have: Set[int] = set(years(c))
            missing = sorted(y for y in set(needed) if y not in have)
            if missing:
                result[c.get("name", "")] = missing
    return result
