"""農曆日期文字（需要 zhdate，沒有安裝時回傳空字串）。"""
import re
from datetime import date, datetime
from functools import lru_cache

_DAY = re.compile(r"(闰|閏)?([正一二三四五六七八九十冬腊臘]+)月(.+)$")


def _tidy_day(day: str) -> str:
    if day.startswith("二十") and len(day) == 3:
        return "廿" + day[2]
    return day


@lru_cache(maxsize=1024)  # 月曆每次重畫都會用到，同一天不用重算
def lunar_text(d: date) -> str:
    """例如 2026-10-03 → 「八月廿三」。"""
    try:
        from zhdate import ZhDate
        text = ZhDate.from_datetime(datetime(d.year, d.month, d.day)).chinese().split(" ")[0]
    except Exception:
        return ""
    text = re.sub(r"^.*?年", "", text)
    m = _DAY.match(text)
    if not m:
        return ""
    leap, month, day = m.groups()
    month = month.replace("腊", "臘")
    return f"{'閏' if leap else ''}{month}月{_tidy_day(day)}"
