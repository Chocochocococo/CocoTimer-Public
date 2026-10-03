"""任務的狀態與資料更新規則（新增、編輯、提醒視窗都走這裡，確保資料一致）。

狀態與完成度的關係：
- 狀態只要不是「進行中」，完成度一律是 100%。
- 完成度到 100% 但狀態還是「進行中」時，自動改成「已交付」。
"""
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from . import billing, holidays, payment_terms
from .models import BillingConfig, Client, TaskItem

IN_PROGRESS, DELIVERED, INVOICED, PAID = "in_progress", "delivered", "invoiced", "paid"
STATUSES = [(IN_PROGRESS, "進行中"), (DELIVERED, "已交付"), (INVOICED, "已請款"), (PAID, "已收款")]
STATUS_LABELS = dict(STATUSES)
_ORDER = [s for s, _ in STATUSES]
_DATE_FIELDS = {DELIVERED: "delivered_date", INVOICED: "invoiced_date", PAID: "paid_date"}

# 對話框可以改的欄位
EDITABLE_FIELDS = ("project_name", "title", "due_date", "due_time", "client", "currency",
                   "description", "completion", "price_items", "remind_before", "status",
                   "settlement_date", "payment_date", "billing_dates_auto")


def _today(today: Optional[str]) -> str:
    return today or date.today().isoformat()


def set_status(task: TaskItem, status: str, today: Optional[str] = None) -> None:
    """切換狀態：補上這一步之前的日期，清掉之後的日期。"""
    if status not in STATUS_LABELS:
        status = IN_PROGRESS
    reached = _ORDER.index(status)
    task.status = status
    for step, attr in _DATE_FIELDS.items():
        if _ORDER.index(step) <= reached:
            if not getattr(task, attr):
                setattr(task, attr, _today(today))
        else:
            setattr(task, attr, "")
    if status != IN_PROGRESS:
        task.completion = 100


def sync_status(task: TaskItem, today: Optional[str] = None) -> None:
    if task.status not in STATUS_LABELS:
        task.status = IN_PROGRESS
    if task.status != IN_PROGRESS:
        set_status(task, task.status, today)
    elif task.completion >= 100:
        set_status(task, DELIVERED, today)


def find_client(clients: List[Client], client_id: str = "", name: str = "") -> Optional[Client]:
    for c in clients:
        if client_id and c.id == client_id:
            return c
    name = (name or "").strip()
    for c in clients:
        if name and c.name.strip() == name:
            return c
    return None


def resolve_client(clients: List[Client], name: str, currency: str = "NTD") -> Tuple[str, bool]:
    """用名稱找客戶，找不到就新增一位。回傳 (客戶 id, 是否新增了客戶)。"""
    name = (name or "").strip()
    if not name:
        return "", False
    found = find_client(clients, name=name)
    if found:
        return found.id, False
    client = Client(id=billing.new_id(), name=name, currency=currency or "NTD")
    clients.append(client)
    return client.id, True


def update_billing_dates(task: TaskItem, client: Optional[Client], config: Optional[BillingConfig],
                         calendars: Optional[List[dict]] = None) -> bool:
    """自動模式下，依交件日、客戶規則與假日行事曆重新計算結算日、收款日。回傳是否有變動。"""
    if not task.billing_dates_auto:
        return False
    rule = config.rule_for(client) if config else payment_terms.normalize_rule(None)
    is_off = holidays.make_is_off(calendars or [], rule["calendar_ids"])
    dates = payment_terms.compute_dates(task.due_date, rule, is_off)
    if dates == (task.settlement_date, task.payment_date):
        return False
    task.settlement_date, task.payment_date = dates
    return True


def recompute_billing_dates(tasks: List[TaskItem], clients: List[Client], config: BillingConfig,
                            calendars: Optional[List[dict]] = None) -> bool:
    """結算規則或假日改變後，重算所有還沒收款、且設為自動計算的任務。"""
    changed = False
    for task in tasks:
        if task.status != PAID:
            client = find_client(clients, task.client_id, task.client)
            changed = update_billing_dates(task, client, config, calendars) or changed
    return changed


def apply_task_data(task: TaskItem, data: dict, clients: List[Client],
                    today: Optional[str] = None, config: Optional[BillingConfig] = None,
                    calendars: Optional[List[dict]] = None) -> bool:
    """把對話框的資料套到任務上。回傳客戶清單是否有變動（需要存檔）。"""
    for key in EDITABLE_FIELDS:
        if key in data:
            setattr(task, key, data[key])
    task.price_items = [billing.normalize_item(i) for i in task.price_items]
    task.client = (task.client or "").strip()
    task.client_id, clients_changed = resolve_client(clients, task.client, task.currency)
    update_billing_dates(task, find_client(clients, task.client_id), config, calendars)
    sync_status(task, today)
    return clients_changed


def new_task(data: dict, clients: List[Client], now: Optional[datetime] = None,
             config: Optional[BillingConfig] = None, calendars: Optional[List[dict]] = None) -> Tuple[TaskItem, bool]:
    now = now or datetime.now()
    task = TaskItem(id=str(int(now.timestamp() * 1000)),
                    project_name=data["project_name"], title=data["title"],
                    due_date=data["due_date"], due_time=data["due_time"],
                    created_date=now.strftime("%Y-%m-%d"), created_time=now.strftime("%H:%M"))
    changed = apply_task_data(task, data, clients, now.strftime("%Y-%m-%d"), config, calendars)
    return task, changed


def save_task_edit(data_manager, tasks: List[TaskItem], task: Optional[TaskItem], data: dict) -> TaskItem:
    """新增（task 為 None）或更新任務，並存檔任務與客戶。"""
    clients = data_manager.load_clients()
    config = data_manager.load_billing()
    calendars = data_manager.load_holidays()
    if task is None:
        task, clients_changed = new_task(data, clients, config=config, calendars=calendars)
        tasks.append(task)
    else:
        clients_changed = apply_task_data(task, data, clients, config=config, calendars=calendars)
    if clients_changed:
        data_manager.save_clients(clients)
    data_manager.save_tasks(tasks)
    return task


def update_completion(task: TaskItem, completion: int, today: Optional[str] = None) -> None:
    """提醒視窗調整完成度時使用。"""
    task.completion = completion
    if completion < 100 and task.status != IN_PROGRESS:
        set_status(task, IN_PROGRESS, today)
    sync_status(task, today)


def status_text(task: TaskItem) -> str:
    return STATUS_LABELS.get(task.status, "進行中")


def client_summary(tasks: List[TaskItem], client: Client) -> dict:
    """一位客戶的案件數與各幣別的待收款、已收款。"""
    mine = [t for t in tasks if t.client_id == client.id
            or (not t.client_id and t.client.strip() == client.name.strip())]
    receivable, paid = {}, {}
    for t in mine:
        bucket = paid if t.status == PAID else receivable if t.status in (DELIVERED, INVOICED) else None
        if bucket is not None:
            bucket[t.currency] = round(bucket.get(t.currency, 0.0) + t.get_total_price(), 2)
    return {"count": len(mine),
            "in_progress": sum(1 for t in mine if t.status == IN_PROGRESS),
            "receivable": receivable, "paid": paid}


def rename_client(tasks: List[TaskItem], client: Client) -> bool:
    """客戶改名後，同步更新任務上顯示的客戶名稱。回傳是否有任務被修改。"""
    changed = False
    for t in tasks:
        if t.client_id == client.id and t.client != client.name:
            t.client = client.name
            changed = True
    return changed


def due_info(task: TaskItem, now: Optional[datetime] = None) -> Tuple[str, str]:
    """交件倒數：回傳（文字, 種類）。種類是 overdue / today / soon / normal / done。"""
    now = now or datetime.now()
    if task.status != IN_PROGRESS:
        return status_text(task), "done"
    try:
        due = datetime.strptime(f"{task.due_date} {task.due_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "", "normal"
    delta = due - now
    if delta.total_seconds() < 0:
        days = (now.date() - due.date()).days
        return (f"逾期 {days} 天" if days >= 1 else f"逾期 {int(-delta.total_seconds() // 3600)} 小時"), "overdue"
    if due.date() == now.date():
        hours = int(delta.total_seconds() // 3600)
        return (f"剩 {hours} 小時" if hours >= 1 else f"剩 {int(delta.total_seconds() // 60)} 分鐘"), "today"
    days = (due.date() - now.date()).days
    return (f"剩 {days} 天", "soon" if days <= 2 else "normal")


def upcoming_tasks(tasks: List[TaskItem], limit: int = 5, now: Optional[datetime] = None) -> List[TaskItem]:
    """進行中的任務，依交件時間排序（逾期的會排在最前面）。"""
    pending = [t for t in tasks if t.status == IN_PROGRESS]
    pending.sort(key=lambda t: f"{t.due_date} {t.due_time}")
    return pending[:limit]


def _add(bucket: dict, currency: str, amount: float) -> None:
    bucket[currency] = round(bucket.get(currency, 0.0) + amount, 2)


def month_income(tasks: List[TaskItem], year: int, month: int, today: Optional[date] = None) -> dict:
    """某個月的收入概況（依幣別）：
    - paid：這個月實際收到的（狀態為已收款，收款日期在本月）
    - expected：預計這個月收到、但還沒收到的（已交付或已請款，預計收款日在本月）
    - overdue：預計收款日已過、還沒收到的（不限月份）
    """
    today = today or date.today()
    prefix = f"{year:04d}-{month:02d}"
    result = {"paid": {}, "expected": {}, "overdue": {}}
    for t in tasks:
        amount = t.get_total_price()
        if not amount:
            continue
        currency = t.currency or "NTD"
        if t.status == PAID and t.paid_date.startswith(prefix):
            _add(result["paid"], currency, amount)
        elif t.status in (DELIVERED, INVOICED):
            if t.payment_date.startswith(prefix):
                _add(result["expected"], currency, amount)
            if t.payment_date and t.payment_date < today.isoformat():
                _add(result["overdue"], currency, amount)
    return result


def billing_summary(task: TaskItem) -> str:
    """例如「委託 5,000 → 計費 3,630 字」或「2,400 字」，沒有數量時回傳空字串。"""
    parts = []
    for q in billing.quantity_summary(task.price_items):
        if not q["quantity"] and not q["billable"]:
            continue
        unit = q["unit"]
        if q["quantity"] != q["billable"]:
            parts.append(f"委託 {billing.format_number(q['quantity'])} → 計費 {billing.format_number(q['billable'])} {unit}".strip())
        elif unit:
            parts.append(f"{billing.format_number(q['quantity'])} {unit}")
    return "、".join(parts)


# --- 任務列表的篩選與排序 ---

FILTERS = [("active", "進行中"), ("receivable", "待收款"), ("closed", "已結案"), ("all", "全部")]
SORTS = [("due", "交件日期"), ("amount", "金額（高到低）"), ("client", "客戶"), ("payment", "預計收款日")]
STATUS_CHIPS = {IN_PROGRESS: "blue", DELIVERED: "teal", INVOICED: "purple", PAID: "green"}


def filter_group(task: TaskItem) -> str:
    if task.status == IN_PROGRESS:
        return "active"
    return "closed" if task.status == PAID else "receivable"


def matches(task: TaskItem, query: str) -> bool:
    query = (query or "").strip().lower()
    if not query:
        return True
    haystack = " ".join((task.title, task.project_name, task.client, task.description)).lower()
    return all(word in haystack for word in query.split())


def sort_tasks(tasks: List[TaskItem], key: str) -> List[TaskItem]:
    due = lambda t: f"{t.due_date} {t.due_time}"
    if key == "amount":
        return sorted(tasks, key=lambda t: (-t.get_total_price(), due(t)))
    if key == "client":
        return sorted(tasks, key=lambda t: (t.client or "￿", due(t)))
    if key == "payment":
        return sorted(tasks, key=lambda t: (t.payment_date or "9999", due(t)))
    return sorted(tasks, key=due)


def task_list(tasks: List[TaskItem], group: str = "active", query: str = "", sort: str = "due",
              closed_limit: Optional[int] = None) -> Tuple[List[TaskItem], int]:
    """篩選＋搜尋＋排序。已結案的任務只保留最近 closed_limit 件（依交件日）。
    回傳（要顯示的任務, 因為數量限制而沒顯示的件數）。"""
    found = [t for t in tasks if (group == "all" or filter_group(t) == group) and matches(t, query)]
    hidden = 0
    if closed_limit is not None:
        closed = sorted((t for t in found if t.status == PAID), key=lambda t: f"{t.due_date} {t.due_time}", reverse=True)
        dropped = {t.id for t in closed[closed_limit:]}
        hidden = len(dropped)
        found = [t for t in found if t.id not in dropped]
    if group == "closed" and sort == "due":
        return sorted(found, key=lambda t: f"{t.due_date} {t.due_time}", reverse=True), hidden
    return sort_tasks(found, sort), hidden


def group_counts(tasks: List[TaskItem]) -> dict:
    counts = {key: 0 for key, _ in FILTERS}
    for t in tasks:
        counts[filter_group(t)] += 1
    counts["all"] = len(tasks)
    return counts


def totals_by_currency(tasks: List[TaskItem]) -> dict:
    totals: dict = {}
    for t in tasks:
        amount = t.get_total_price()
        if amount:
            _add(totals, t.currency or "NTD", amount)
    return totals


def payment_info(task: TaskItem, today: Optional[date] = None) -> Tuple[str, str]:
    """待收款任務的收款提示：回傳（文字, 種類），種類是 late / soon / normal / ""。"""
    if task.status not in (DELIVERED, INVOICED) or not task.payment_date:
        return "", ""
    today = today or date.today()
    try:
        due = date.fromisoformat(task.payment_date)
    except ValueError:
        return "", ""
    label = f"預計 {due.month}/{due.day} 收款"
    days = (due - today).days
    if days < 0:
        return f"{label} · 已過 {-days} 天", "late"
    if days <= 7:
        return f"{label} · 還有 {days} 天" if days else f"{label} · 今天", "soon"
    return label, "normal"


# --- 批次修改狀態 ---

BATCH_DATE_FIELDS = [("due_date", "交件日"), ("payment_date", "預計收款日"), ("settlement_date", "結算日")]
BATCH_DATE_MODES = [("expected", "各任務的預計日期"), ("today", "今天"), ("fixed", "指定日期")]
NO_CLIENT = "-"  # 篩選「沒有指定客戶」的任務


def batch_matches(tasks: List[TaskItem], statuses=None, client_ids=None, date_field: str = "due_date",
                  start: str = "", end: str = "") -> List[TaskItem]:
    """批次修改要處理的任務。statuses / client_ids 是 None 表示不限；start、end 是 YYYY-MM-DD（含當天），空白表示不限。
    client_ids 可以包含 NO_CLIENT。指定期間時，沒有該日期的任務不算符合。"""
    found = []
    for t in tasks:
        if statuses is not None and t.status not in statuses:
            continue
        if client_ids is not None and (t.client_id or NO_CLIENT) not in client_ids:
            continue
        if start or end:
            value = getattr(t, date_field, "") or ""
            if not value or (start and value < start) or (end and value > end):
                continue
        found.append(t)
    return sorted(found, key=lambda t: f"{t.due_date} {t.due_time}")


def _expected_date(task: TaskItem, step: str) -> str:
    if step == PAID:
        return task.payment_date or task.settlement_date or task.due_date
    if step == INVOICED:
        return task.settlement_date or task.due_date
    return task.due_date


def apply_batch_status(tasks: List[TaskItem], status: str, date_mode: str = "expected",
                       fixed_date: str = "", today: Optional[str] = None) -> Dict[str, dict]:
    """把 tasks 全部改成 status，回傳修改前的資料 {任務 id: to_dict()}，可以用 restore_tasks 復原。

    已經填過的日期會保留；新填的日期依 date_mode：
    expected 用任務自己的交件日（已交付）、結算日（已請款）、預計收款日（已收款），但不會晚於今天；
    today 用今天；fixed 用 fixed_date。"""
    today = _today(today)
    before = {}
    for task in tasks:
        before[task.id] = task.to_dict()
        if status == IN_PROGRESS:
            update_completion(task, min(task.completion, 90), today)
            continue
        reached = _ORDER.index(status)
        for step, attr in _DATE_FIELDS.items():
            if _ORDER.index(step) <= reached and not getattr(task, attr):
                if date_mode == "fixed" and fixed_date:
                    value = fixed_date
                elif date_mode == "today":
                    value = today
                else:
                    value = min(_expected_date(task, step) or today, today)
                setattr(task, attr, value)
        set_status(task, status, today)
    return before


def restore_tasks(tasks: List[TaskItem], before: Dict[str, dict]) -> int:
    """把 apply_batch_status 改過的任務還原。回傳還原的件數。"""
    restored = 0
    for i, task in enumerate(tasks):
        if task.id in before:
            tasks[i] = TaskItem.from_dict(before[task.id])
            restored += 1
    return restored


# --- 番茄鐘專注時間 ---

def add_focus(task: TaskItem, seconds: float, day: str) -> None:
    if not isinstance(task.focus_log, dict):
        task.focus_log = {}
    task.focus_log[day] = int(task.focus_log.get(day, 0) + max(0, seconds))


def focus_seconds(task: TaskItem, start: str = "", end: str = "") -> int:
    """專注秒數；start、end 是 YYYY-MM-DD（含），空白表示不限。"""
    log = task.focus_log if isinstance(task.focus_log, dict) else {}
    return int(sum(v for d, v in log.items() if isinstance(v, (int, float))
                   and (not start or d >= start) and (not end or d <= end)))


def hourly_rate(task: TaskItem) -> Optional[float]:
    """金額 ÷ 專注時數；專注不到 10 分鐘或沒有金額時回傳 None（數字沒有參考價值）。"""
    seconds = focus_seconds(task)
    amount = task.get_total_price()
    if seconds < 600 or not amount:
        return None
    return amount / (seconds / 3600)


def focus_text(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60} 小時 {minutes % 60:02d} 分" if minutes >= 60 else f"{minutes} 分鐘"
