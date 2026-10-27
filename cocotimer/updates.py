"""檢查 GitHub 上有沒有新版本。

只讀取最新 Release 的版本號，不會下載或執行任何東西；通知裡的連結固定是 RELEASES_URL，
不會用 GitHub 回傳的網址或文字。連線使用系統的憑證驗證 HTTPS，失敗就安靜略過。
"""
import json
import re
import ssl
import urllib.request
from typing import Optional, Tuple

from . import __version__

LATEST_API = "https://api.github.com/repos/Chocochocococo/CocoTimer-Public/releases/latest"
MAX_BYTES = 512 * 1024
TIMEOUT = 10


def parse_version(text) -> Optional[Tuple[int, int, int]]:
    """"v3.2"、"V3.1.1"、"3.3.0" → (3, 2, 0)…；格式不對就回傳 None。"""
    match = re.fullmatch(r"[vV]?(\d{1,4})\.(\d{1,4})(?:\.(\d{1,4}))?", str(text or "").strip())
    if not match:
        return None
    return int(match[1]), int(match[2]), int(match[3] or 0)


def is_newer(version: str, current: str = __version__) -> bool:
    found, mine = parse_version(version), parse_version(current)
    return bool(found and mine and found > mine)


def latest_from_response(data) -> Optional[str]:
    """從 GitHub API 的回應取出版本號（只看 tag_name）。"""
    version = parse_version(data.get("tag_name")) if isinstance(data, dict) else None
    return ".".join(map(str, version)) if version else None


def fetch_latest(timeout: float = TIMEOUT) -> Optional[str]:
    """回傳 GitHub 上最新版的版本號，例如 "3.3.0"；連不上或內容不對時回傳 None。"""
    request = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": "CocoTimer"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
            data = json.loads(response.read(MAX_BYTES))
    except (OSError, ValueError):  # 沒網路、逾時、憑證不對、內容不是 JSON
        return None
    return latest_from_response(data)
