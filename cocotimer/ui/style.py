"""整個程式用的 Qt 風格：Fusion，加上數字欄位的修正。

Qt 6.12.0 和 6.11.3 的樣式表在計算數字欄位（QSpinBox、QTimeEdit…）的文字區時有錯（QTBUG-151308，
6.12.1 修正）：左邊內距被忽略，隱藏上下按鈕的欄位寬度只剩 1px，數字完全看不見。
這裡在每個數字欄位建立時掛上修正，文字區被放錯時改回正確的位置；沒有這個問題的 Qt 版本不會有任何改變。
"""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractSpinBox, QDateTimeEdit, QLineEdit, QProxyStyle

from cocotimer.theme import INPUT_BORDER, INPUT_PADDING_X, SPIN_BUTTON_WIDTH

INSET = INPUT_BORDER + INPUT_PADDING_X


class _EditFieldFix(QObject):
    def eventFilter(self, edit, event):
        if event.type() in (QEvent.Resize, QEvent.Move):
            spin = edit.parentWidget()
            rect = edit.geometry()
            popup = isinstance(spin, QDateTimeEdit) and spin.calendarPopup()  # 有下拉月曆的日期欄位不受影響
            # 出錯的版本會把文字區的左邊放在 0；用了樣式表的欄位，正確的左邊是框線加內距
            if rect.left() == 0 and not popup and spin.style().metaObject().className() == "QStyleSheetStyle":
                buttons = 0 if spin.buttonSymbols() == QAbstractSpinBox.NoButtons else SPIN_BUTTON_WIDTH
                rect.setLeft(INSET)
                rect.setRight(spin.width() - 1 - INSET - buttons)
                edit.setGeometry(rect)
        return False


class AppStyle(QProxyStyle):
    def __init__(self):
        super().__init__("Fusion")
        self._fix = _EditFieldFix(self)

    def polish(self, target):
        result = super().polish(target)
        if isinstance(target, QAbstractSpinBox):
            edit = target.findChild(QLineEdit)
            if edit is not None and not edit.property("editFieldFix"):
                edit.setProperty("editFieldFix", True)
                edit.installEventFilter(self._fix)
        return result
