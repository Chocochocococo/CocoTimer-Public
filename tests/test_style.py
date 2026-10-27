import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDateEdit, QSpinBox, QTimeEdit, QVBoxLayout, QWidget

from cocotimer import theme
from cocotimer.models import ThemeConfig
from cocotimer.ui.billing_widgets import number_box
from cocotimer.ui.style import INSET, AppStyle


def test_number_fields_show_their_text():
    """Qt 6.12.0／6.11.3 的樣式表會把數字欄位的文字區縮成 1px（QTBUG-151308），AppStyle 要把它改回來。"""
    app = QApplication.instance() or QApplication([])
    app.setStyle(AppStyle())
    page = QWidget()
    page.setStyleSheet(theme.stylesheet(ThemeConfig()))
    layout = QVBoxLayout(page)
    price, spin, time = number_box(), QSpinBox(), QTimeEdit()
    date = QDateEdit()
    date.setCalendarPopup(True)
    for box in (price, spin, time, date):
        box.setFixedWidth(140)
        layout.addWidget(box)
    page.show()
    app.processEvents()
    buttons = theme.SPIN_BUTTON_WIDTH
    assert price.lineEdit().geometry().left() == INSET and price.lineEdit().width() == 140 - 2 * INSET
    for box in (spin, time):
        assert box.lineEdit().geometry().left() == INSET and box.lineEdit().width() == 140 - 2 * INSET - buttons
    assert date.lineEdit().width() > 60
    price.setFixedWidth(180)
    app.processEvents()
    assert price.lineEdit().width() == 180 - 2 * INSET  # 欄位變寬之後也正確
    page.close()
