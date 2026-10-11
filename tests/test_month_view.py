import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from cocotimer import theme
from cocotimer.models import ThemeConfig
from cocotimer.ui.month_view import MonthView


def test_selected_day_after_today_is_not_filled_with_accent():
    """今天的圓圈用強調色筆刷；之後選到的日子只描邊，不會整格塗滿強調色。"""
    app = QApplication.instance() or QApplication([])
    view = MonthView()
    view.set_colors(theme.tokens(ThemeConfig.from_dict(theme.PRESETS["可可深色"])), dark=True)
    view.resize(700, 600)
    view.set_month(2026, 10)
    view.today = date(2026, 10, 11)
    view.set_selected(date(2026, 10, 25))
    image = view.grab().toImage()
    head, cw, ch = view._metrics()
    index = view.days.index(date(2026, 10, 25))
    row, col = divmod(index, 7)
    center = image.pixelColor(int((col + 0.5) * cw), int(head + (row + 0.75) * ch))
    assert center != QColor(theme.PRESETS["可可深色"]["accent_color"])
    assert center == QColor(view._palette()["soft"])
    app.processEvents()
