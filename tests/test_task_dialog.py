import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QMessageBox

from cocotimer.data_manager import DataManager
from cocotimer.ui.task_dialog import TaskEditDialog


def test_milestones_round_trip_and_must_be_before_final(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))
    dialog = TaskEditDialog(DataManager(str(tmp_path)))
    dialog.project_input.setText("星海旅人")
    dialog.title_input.setText("封面")
    dialog.due_date_input.setDate(QDate(2026, 11, 30))
    assert dialog.due_title.text() == "交件日期與時間"
    row = dialog._add_milestone()
    row.name_input.setText("草稿")
    row.date_input.setDate(QDate(2026, 11, 10))
    assert dialog.due_title.text() == "最後交件日期與時間"
    assert dialog._validate_required_fields()
    assert dialog.get_task_data()["milestones"][0]["name"] == "草稿"
    row.date_input.setDate(QDate(2026, 12, 2))
    assert not dialog._validate_required_fields() and "草稿" in warnings[-1]
    dialog._remove_milestone(row)
    assert dialog.get_task_data()["milestones"] == [] and dialog.due_title.text() == "交件日期與時間"
    dialog.deleteLater()
    app.processEvents()
