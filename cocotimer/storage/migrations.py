"""資料格式版本與升級。

資料夾裡的 ``meta.json`` 記錄資料格式版本。v2 沒有這個檔，所以「有資料檔但沒有
meta.json」就視為 v2。升級前會先做一次永久保留的快照備份。
"""
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Callable, Dict, Optional

from .backup import snapshot
from .jsonstore import JsonFileStore

CURRENT_SCHEMA = 8
# 升級時，完成超過這麼多天的舊任務視為已收款，較近的視為已交付（待收款）
PAID_AFTER_DAYS = 90
META_FILE = "meta.json"
LEGACY_FILES = ("events.json", "tasks.json", "work_records.json", "settings.json")


def detect_schema(store: JsonFileStore) -> int:
    meta = store.read(META_FILE, dict) if store.exists(META_FILE) else {}
    if isinstance(meta, dict) and isinstance(meta.get("schema_version"), int):
        return meta["schema_version"]
    if any(store.exists(name) for name in LEGACY_FILES):
        return 2
    return CURRENT_SCHEMA


def _to_number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _v2_to_v3(store: JsonFileStore) -> None:
    """v2 → v3：整理價格項目的數值型別，其餘欄位交給資料模型補預設值。"""
    if store.exists("tasks.json"):
        tasks = store.read("tasks.json", list)
        if isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                items = task.get("price_items")
                if not isinstance(items, list):
                    task["price_items"] = []
                    continue
                task["price_items"] = [
                    {**item,
                     "unit_price": _to_number(item.get("unit_price"), 0.0),
                     "quantity": _to_number(item.get("quantity"), 1.0)}
                    for item in items if isinstance(item, dict)
                ]
            store.write("tasks.json", tasks)


def _status_for_legacy(task: dict, today: date) -> str:
    try:
        completion = float(task.get("completion", 0))
    except (TypeError, ValueError):
        completion = 0
    if completion < 100:
        return "in_progress"
    try:
        due = datetime.strptime(task.get("due_date", ""), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return "delivered"
    return "paid" if due < today - timedelta(days=PAID_AFTER_DAYS) else "delivered"


def _v3_to_v4(store: JsonFileStore, today: Optional[date] = None) -> None:
    """v3 → v4：價格項目加上單位與計費方式、任務加上狀態、從任務的客戶名稱建立客戶清單、
    建立通用範本與預設加權表。"""
    from .. import billing  # 避免 storage 在載入時就依賴計費模組

    today = today or date.today()
    tasks = store.read("tasks.json", list) if store.exists("tasks.json") else []
    if not isinstance(tasks, list):
        tasks = []

    clients = store.read("clients.json", list) if store.exists("clients.json") else []
    if not isinstance(clients, list):
        clients = []
    by_name = {c.get("name", "").strip(): c for c in clients if isinstance(c, dict)}
    currencies: Dict[str, Counter] = {}  # 只用來決定新建立客戶的預設幣別

    for task in tasks:
        if not isinstance(task, dict):
            continue
        task["price_items"] = [billing.normalize_item(i) for i in task.get("price_items", []) if isinstance(i, dict)]
        if "status" not in task:
            task["status"] = _status_for_legacy(task, today)
            for attr in ("delivered_date", "invoiced_date", "paid_date"):
                task.setdefault(attr, "")
        name = (task.get("client") or "").strip()
        if name:
            if name not in by_name:
                by_name[name] = {"id": uuid.uuid4().hex[:12], "name": name, "contact": "", "email": "",
                                 "currency": "NTD", "payment_terms": "", "notes": "",
                                 "weighting_profile_id": "", "rates": [], "archived": False}
                clients.append(by_name[name])
                currencies[name] = Counter()
            task["client_id"] = by_name[name]["id"]
            if name in currencies:
                currencies[name][task.get("currency") or "NTD"] += 1

    for name, counter in currencies.items():
        by_name[name]["currency"] = counter.most_common(1)[0][0]

    store.write("tasks.json", tasks)
    store.write("clients.json", clients)
    if not store.exists("billing.json"):
        profile = billing.default_weighting_profile()
        store.write("billing.json", {"rates": [], "weighting_profiles": [profile],
                                     "default_weighting_profile_id": profile["id"]})


def _v4_to_v5(store: JsonFileStore) -> None:
    """v4 → v5：加上結算與收款規則（預設月底結算、次月 1 日收款），並幫舊任務算出結算日與收款日。"""
    from .. import payment_terms

    config = store.read("billing.json", dict) if store.exists("billing.json") else {}
    if not isinstance(config, dict):
        config = {}
    config.setdefault("payment_rule", dict(payment_terms.DEFAULT_RULE))
    store.write("billing.json", config)

    if not store.exists("tasks.json"):
        return
    tasks = store.read("tasks.json", list)
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if isinstance(task, dict) and "settlement_date" not in task:
            task["billing_dates_auto"] = True
            task["settlement_date"], task["payment_date"] = payment_terms.compute_dates(
                task.get("due_date", ""), config["payment_rule"])
    store.write("tasks.json", tasks)


def _v5_to_v6(store: JsonFileStore) -> None:
    """v5 → v6：加入假日行事曆（內建台灣國定假日），結算規則改用行事曆判斷假日，
    並重算還沒收款、自動計算的任務日期。"""
    from .. import holidays, payment_terms

    calendars = _read_list(store, "holidays.json", "calendars")
    if not calendars:
        calendars = [holidays.taiwan_calendar()]
        store.write("holidays.json", {"calendars": calendars})
    taiwan_id = calendars[0]["id"]

    config = store.read("billing.json", dict) if store.exists("billing.json") else {}
    if not isinstance(config, dict):
        config = {}
    rule = config.get("payment_rule") if isinstance(config.get("payment_rule"), dict) else dict(payment_terms.DEFAULT_RULE)
    rule.setdefault("calendar_ids", [taiwan_id])
    config["payment_rule"] = rule
    store.write("billing.json", config)

    clients = _read_list(store, "clients.json")
    for client in clients:
        if isinstance(client, dict) and isinstance(client.get("payment_rule"), dict):
            client["payment_rule"].setdefault("calendar_ids", [taiwan_id])
    if clients:
        store.write("clients.json", clients)

    tasks = _read_list(store, "tasks.json")
    by_id = {c.get("id"): c for c in clients if isinstance(c, dict)}
    for task in tasks:
        if not isinstance(task, dict) or not task.get("billing_dates_auto", True) or task.get("status") == "paid":
            continue
        client = by_id.get(task.get("client_id"))
        task_rule = client["payment_rule"] if client and isinstance(client.get("payment_rule"), dict) else rule
        is_off = holidays.make_is_off(calendars, payment_terms.normalize_rule(task_rule)["calendar_ids"])
        task["settlement_date"], task["payment_date"] = payment_terms.compute_dates(
            task.get("due_date", ""), task_rule, is_off)
    if tasks:
        store.write("tasks.json", tasks)


def _read_list(store: JsonFileStore, name: str, key: Optional[str] = None) -> list:
    if not store.exists(name):
        return []
    data = store.read(name, dict if key else list)
    if key:
        data = data.get(key) if isinstance(data, dict) else None
    return data if isinstance(data, list) else []


def ensure_defaults(store: JsonFileStore) -> None:
    """全新的資料夾也要有內建的台灣行事曆、加權表與結算規則。"""
    from .. import billing, holidays, payment_terms

    calendars = _read_list(store, "holidays.json", "calendars")
    if not store.exists("holidays.json"):
        calendars = [holidays.taiwan_calendar()]
        store.write("holidays.json", {"calendars": calendars})
    if not store.exists("billing.json"):
        profile = billing.default_weighting_profile()
        rule = dict(payment_terms.DEFAULT_RULE)
        rule["calendar_ids"] = [calendars[0]["id"]] if calendars else []
        store.write("billing.json", {"rates": [], "weighting_profiles": [profile],
                                     "default_weighting_profile_id": profile["id"], "payment_rule": rule})


def _v6_to_v7(store: JsonFileStore) -> None:
    """v6 → v7：新介面的配色。從沒改過顏色（仍是 v2 預設）的使用者換成 v3 配色；
    改過的保留原本的顏色，只補上新增的顏色欄位。"""
    from .. import theme as theme_module

    if not store.exists("settings.json"):
        return
    settings = store.read("settings.json", dict)
    if not isinstance(settings, dict):
        return
    current = settings.get("theme") if isinstance(settings.get("theme"), dict) else {}
    untouched = all(str(current.get(k, v)).upper() == v.upper() for k, v in theme_module.V2_DEFAULT_COLORS.items())
    preset = theme_module.PRESETS[theme_module.DEFAULT_PRESET if untouched else "v2 經典"]
    if untouched:
        current.update(preset)
    else:
        for key in ("surface_color", "sidebar_color", "muted_color", "accent_text_color"):
            current.setdefault(key, preset[key])
    settings["theme"] = current
    store.write("settings.json", settings)


def _v7_to_v8(store: JsonFileStore, today: Optional[date] = None) -> None:
    """v7 → v8：從 v2 升級的舊任務被判定成「已交付／已收款」時沒有填日期，統計就算不到它們。
    補上估計的日期：交付日用交件日；收款日用預計收款日（照客戶目前的結帳規則重算），都不晚於今天。
    已經有的日期不動。"""
    from .. import holidays, payment_terms

    tasks = _read_list(store, "tasks.json")
    if not tasks:
        return
    today_text = (today or date.today()).isoformat()
    calendars = _read_list(store, "holidays.json", "calendars")
    config = store.read("billing.json", dict) if store.exists("billing.json") else {}
    rule = config.get("payment_rule") if isinstance(config, dict) and isinstance(config.get("payment_rule"), dict) \
        else dict(payment_terms.DEFAULT_RULE)
    by_id = {c.get("id"): c for c in _read_list(store, "clients.json") if isinstance(c, dict)}
    order = ["delivered", "invoiced", "paid"]
    changed = False
    for task in tasks:
        if not isinstance(task, dict) or task.get("status") not in order:
            continue
        due = task.get("due_date") or task.get("created_date") or ""
        if not isinstance(due, str) or len(due) < 10:
            continue
        due = due[:10]
        reached = order.index(task["status"])
        missing = [attr for step, attr in zip(order, ("delivered_date", "invoiced_date", "paid_date"))
                   if order.index(step) <= reached and not task.get(attr)]
        if not missing:
            continue
        if "paid_date" in missing and task.get("billing_dates_auto", True):
            client = by_id.get(task.get("client_id"))
            task_rule = client["payment_rule"] if client and isinstance(client.get("payment_rule"), dict) else rule
            is_off = holidays.make_is_off(calendars, payment_terms.normalize_rule(task_rule)["calendar_ids"])
            task["settlement_date"], task["payment_date"] = payment_terms.compute_dates(due, task_rule, is_off)
        guesses = {"delivered_date": due, "invoiced_date": task.get("settlement_date") or due,
                   "paid_date": task.get("payment_date") or task.get("settlement_date") or due}
        for attr in missing:
            task[attr] = min(guesses[attr], today_text)
        changed = True
    if changed:
        store.write("tasks.json", tasks)


MIGRATIONS: Dict[int, Callable[[JsonFileStore], None]] = {
    2: _v2_to_v3,
    3: _v3_to_v4,
    4: _v4_to_v5,
    5: _v5_to_v6,
    6: _v6_to_v7,
    7: _v7_to_v8,
}


def migrate(store: JsonFileStore, app_version: str) -> int:
    """把資料升級到目前版本，回傳升級前的版本。"""
    version = detect_schema(store)
    if version > CURRENT_SCHEMA:
        store.problems.append(
            f"這份資料來自較新版本的 CocoTimer（資料格式 v{version}），"
            f"目前版本只支援到 v{CURRENT_SCHEMA}，部分新功能的資料可能無法顯示。")
        return version
    if version < CURRENT_SCHEMA:
        snapshot(store.data_dir, f"before-v{CURRENT_SCHEMA}")
        for v in range(version, CURRENT_SCHEMA):
            MIGRATIONS[v](store)
    ensure_defaults(store)
    if version < CURRENT_SCHEMA or not store.exists(META_FILE):
        store.write(META_FILE, {"schema_version": CURRENT_SCHEMA, "app_version": app_version})
    return version
