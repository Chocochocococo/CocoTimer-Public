import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QPushButton

from cocotimer import SPONSOR_LINKS
from cocotimer.ui.settings_page import SponsorDialog


def test_sponsor_dialog_opens_each_link(monkeypatch):
    app = QApplication.instance() or QApplication([])
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    dialog = SponsorDialog()
    buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
    for name, _url in SPONSOR_LINKS:
        buttons[name].click()
    assert opened == [url for _name, url in SPONSOR_LINKS]
    assert all(url.startswith("https://") for url in opened)
    dialog.deleteLater()
    app.processEvents()
