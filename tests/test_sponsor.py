import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QWidget

from cocotimer import SPONSOR_LINKS
from cocotimer.ui.settings_page import SponsorDialog


def test_sponsor_links_open_and_close_the_dialog(monkeypatch):
    app = QApplication.instance() or QApplication([])
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    for name, url in SPONSOR_LINKS:
        dialog = SponsorDialog()
        dialog.show()
        {b.text(): b for b in dialog.findChildren(QPushButton)}[name].click()
        assert opened[-1] == url and url.startswith("https://")
        assert dialog.result() == QDialog.Accepted and not dialog.isVisible()  # 開了瀏覽器就關掉，不會卡住側邊停靠
        dialog.deleteLater()
    app.processEvents()


def test_sponsor_dialog_stays_above_a_topmost_window():
    app = QApplication.instance() or QApplication([])
    panel = QWidget()
    panel.setWindowFlags(Qt.Window | Qt.Tool | Qt.WindowStaysOnTopHint)
    assert SponsorDialog(panel).windowFlags() & Qt.WindowStaysOnTopHint
    assert not SponsorDialog(QWidget()).windowFlags() & Qt.WindowStaysOnTopHint
    app.processEvents()
