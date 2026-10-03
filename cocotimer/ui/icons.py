"""線條圖示：用 SVG 路徑畫成任意顏色的 QIcon（24×24 座標）。"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "today": "M16 12a4 4 0 1 1-8 0a4 4 0 1 1 8 0M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
    "calendar": "M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM3 10h18M8 3v4M16 3v4",
    "tasks": "M6 3h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM8 9l2 2 4-4M8 16h8",
    "clients": "M12.5 8a3.5 3.5 0 1 1-7 0a3.5 3.5 0 1 1 7 0M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2.2.6 3.5 2.6 3.5 6",
    "work": "M20 13a8 8 0 1 1-16 0a8 8 0 1 1 16 0M12 9v4l2.5 2.5M9 2h6",
    "stats": "M6 17v-6M12 17V7M18 17v-4M3 21h18",
    "settings": "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M18 6a2 2 0 1 1-4 0a2 2 0 1 1 4 0M12 12a2 2 0 1 1-4 0a2 2 0 1 1 4 0M20 18a2 2 0 1 1-4 0a2 2 0 1 1 4 0",
    "menu": "M4 7h16M4 12h16M4 17h16",
    "collapse": "M11 6l-6 6 6 6M19 6l-6 6 6 6",
    "plus": "M12 5v14M5 12h14",
    "skip": "M5 5l9 7-9 7zM18 5v14",
    "reset": "M4 4v5h5M5.5 15a7 7 0 1 0 1.2-7.4L4 9",
    "clock": "M20 12a8 8 0 1 1-16 0a8 8 0 1 1 16 0M12 8v4l3 2",
    "week": "M5 8h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2zM8 8v8M12 8v8M16 8v8",
    "pomodoro": "M19 14a7 7 0 1 1-14 0a7 7 0 1 1 14 0M12 7V4M9 5.5l3 1.5 3-1.5",
    "bar": "M6 9h12a3 3 0 0 1 0 6H6a3 3 0 0 1 0-6zM10 9v6M14 9v6",
    "lock": "M7 11h10a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-6a2 2 0 0 1 2-2zM8 11V8a4 4 0 0 1 8 0v3",
    "droplet": "M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z",
    "chevron_left": "M15 6l-6 6 6 6",
    "chevron_right": "M9 6l6 6-6 6",
    "close": "M6 6l12 12M18 6L6 18",
    "search": "M18 11a7 7 0 1 1-14 0a7 7 0 1 1 14 0M20 20l-3.5-3.5",
    "dock": "M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM15 4v16M18 10v4",
    "pin": "M9 4h6M10 4v5l-3 4h10l-3-4V4M12 13v7",
    "popout": "M14 4h6v6M20 4l-8 8M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4",
    "window": "M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM3 9h18M6.5 6.5h.01M9 6.5h.01",
}
FILLED = {
    "play": "M7 4.5v15l12-7.5z",
    "pause": "M6 5h4v14H6zM14 5h4v14h-4z",
}


@lru_cache(maxsize=256)
def _pixmap(name: str, color: str, size: int, ratio: float) -> QPixmap:
    if name in FILLED:
        body = f'<path d="{FILLED[name]}" fill="{color}"/>'
    else:
        body = (f'<path d="{PATHS[name]}" fill="none" stroke="{color}" stroke-width="1.8" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pixel = round(size * ratio)
    pixmap = QPixmap(pixel, pixel)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, pixel, pixel))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def icon(name: str, color: str, size: int = 20) -> QIcon:
    app = QGuiApplication.instance()
    ratio = app.devicePixelRatio() if app else 1.0
    return QIcon(_pixmap(name, color, size, max(1.0, ratio)))
