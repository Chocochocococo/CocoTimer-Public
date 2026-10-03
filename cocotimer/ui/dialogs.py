from datetime import datetime

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

from cocotimer.models import Event


class EventEditDialog(QDialog):
    """新增／編輯行程。編輯時會直接修改傳入的 event_data；新增時用 get_event() 取得新行程。
    preset_date（可省略）是新增時預設的日期；on_delete（可省略）會在按「刪除行程」並確認後呼叫。"""

    def __init__(self, data_manager, event_data=None, parent=None, preset_date=None, on_delete=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.event_data = event_data
        self.on_delete = on_delete
        self.setWindowTitle("編輯行程" if event_data else "新增行程")
        self.setMinimumSize(420, 400)
        self._build_ui()
        if self.event_data:
            self._load_event_data()
        elif preset_date is not None:
            self.date_input.setDate(QDate(preset_date.year, preset_date.month, preset_date.day))
            if preset_date != datetime.now().date():
                self.time_input.setTime(QTime(9, 0))
        self.data_manager.restore_window_geometry("event_edit_dialog", self)
        if self.width() < 420 or self.height() < 400:
            self.resize(520, 460)
        self.title_input.setFocus()

    def _build_ui(self):
        from cocotimer.ui.widgets import button, card, label

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        content.setObjectName("contentArea")
        body = QVBoxLayout(content)
        body.setContentsMargins(24, 20, 24, 20)
        body.setSpacing(14)
        title = QLabel(self.windowTitle())
        title.setObjectName("pageTitle")
        body.addWidget(title)

        section = card(spacing=12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        def field(text, widget):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(5)
            lab = label(text, muted=True)
            lab.setBuddy(widget)
            v.addWidget(lab)
            v.addWidget(widget)
            return box

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("例如：和出版社開會")
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy/MM/dd")
        self.time_input = QTimeEdit(QTime.currentTime())
        self.time_input.setDisplayFormat("HH:mm")
        grid.addWidget(field("標題", self.title_input), 0, 0, 1, 2)
        grid.addWidget(field("日期", self.date_input), 1, 0)
        grid.addWidget(field("時間（到這個時間會提醒）", self.time_input), 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        section.layout().addLayout(grid)
        self.desc_input = QTextEdit()
        self.desc_input.setMinimumHeight(70)
        self.desc_input.setPlaceholderText("地點、連結或其他說明（可分行）")
        self.desc_input.setTabChangesFocus(True)
        section.layout().addWidget(field("描述", self.desc_input), 1)
        self.completed_checkbox = QCheckBox("已完成")
        section.layout().addWidget(self.completed_checkbox)
        body.addWidget(section, 1)
        layout.addWidget(content, 1)

        footer = QFrame()
        footer.setProperty("card", True)
        footer.setStyleSheet("QFrame { border-radius: 0; border-left: none; border-right: none; border-bottom: none; }")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(20, 12, 20, 12)
        if self.event_data and self.on_delete:
            delete_btn = button("刪除行程", link=True, danger=True)
            delete_btn.clicked.connect(self._delete)
            buttons.addWidget(delete_btn)
        buttons.addStretch()
        cancel_btn = button("取消")
        cancel_btn.setMinimumWidth(96)
        cancel_btn.clicked.connect(self.reject)
        save_btn = button("儲存", primary=True)
        save_btn.setMinimumWidth(110)
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save_clicked)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        layout.addWidget(footer)

    def _delete(self):
        if QMessageBox.question(self, "刪除行程", f"確定要刪除「{self.event_data.title}」嗎？",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.on_delete(self.event_data)
            self.reject()

    def _load_event_data(self):
        """載入事件資料到表單"""
        self.title_input.setText(self.event_data.title)
        self.date_input.setDate(QDate.fromString(self.event_data.date, "yyyy-MM-dd"))
        self.time_input.setTime(QTime.fromString(self.event_data.time, "HH:mm"))
        self.desc_input.setText(self.event_data.description)
        self.completed_checkbox.setChecked(self.event_data.completed)

    def _on_save_clicked(self):
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "還沒填標題", "請輸入行程標題！")
            self.title_input.setFocus()
            return
        new_date = self.date_input.date().toString("yyyy-MM-dd")
        new_time = self.time_input.time().toString("HH:mm")
        is_past = datetime.now() > datetime.strptime(f"{new_date} {new_time}", "%Y-%m-%d %H:%M")
        if self.event_data:
            if is_past:
                self.event_data.notified = True
            elif self.event_data.notified:
                self.event_data.notified = False
            self.event_data.title = self.title_input.text().strip()
            self.event_data.date = new_date
            self.event_data.time = new_time
            self.event_data.description = self.desc_input.toPlainText().strip()
            self.event_data.completed = self.completed_checkbox.isChecked()
        else:
            import uuid
            self.event_data = Event(
                id=uuid.uuid4().hex,
                title=self.title_input.text().strip(),
                date=new_date,
                time=new_time,
                description=self.desc_input.toPlainText().strip(),
                completed=self.completed_checkbox.isChecked(),
                notified=is_past,
            )
        self.accept()

    def get_event(self):
        """獲取編輯後的事件"""
        return self.event_data


class WorkSessionEditDialog(QDialog):
    """工時記錄編輯對話框"""
    def __init__(self, data_manager, date_str, sessions=None, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.date_str = date_str
        self.sessions = sessions if sessions else []
        self.setWindowTitle(f"編輯工時 - {date_str}")
        self.setMinimumSize(600, 400)
        self._build_ui()
        self._load_sessions()
        self.data_manager.restore_window_geometry("work_session_edit_dialog", self)
        if self.width() < 600 or self.height() < 400:
            self.resize(700, 500)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 標題
        title_label = QLabel(f"📅 日期: {self.date_str}")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title_label)

        # 工時列表
        list_label = QLabel("工時記錄:")
        layout.addWidget(list_label)

        self.sessions_tree = QTreeWidget()
        self.sessions_tree.setHeaderLabels(["開始時間", "結束時間", "時長(小時)"])
        self.sessions_tree.setColumnWidth(0, 200)
        self.sessions_tree.setColumnWidth(1, 200)
        layout.addWidget(self.sessions_tree)

        # 按鈕
        button_layout = QHBoxLayout()
        add_btn = QPushButton("新增記錄")
        add_btn.clicked.connect(self._add_session)
        edit_btn = QPushButton("編輯選中")
        edit_btn.clicked.connect(self._edit_session)
        delete_btn = QPushButton("刪除選中")
        delete_btn.clicked.connect(self._delete_session)
        button_layout.addWidget(add_btn)
        button_layout.addWidget(edit_btn)
        button_layout.addWidget(delete_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        layout.addStretch()

        # 關閉按鈕
        close_layout = QHBoxLayout()
        close_layout.addStretch()
        save_btn = QPushButton("儲存")
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self._on_save_clicked)
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        close_layout.addWidget(save_btn)
        close_layout.addWidget(cancel_btn)
        layout.addLayout(close_layout)

    def _load_sessions(self):
        """載入工時記錄到列表"""
        self.sessions_tree.clear()
        for session in self.sessions:
            start = session.get('start', '')
            end = session.get('end', '')
            duration = ""
            if start and end:
                try:
                    sd = datetime.fromisoformat(start)
                    ed = datetime.fromisoformat(end)
                    duration_hours = (ed - sd).total_seconds() / 3600
                    duration = f"{duration_hours:.2f}"
                    start_display = sd.strftime("%Y-%m-%d %H:%M:%S")
                    end_display = ed.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    start_display = start
                    end_display = end
            else:
                start_display = start
                end_display = end if end else "進行中"

            item = QTreeWidgetItem([start_display, end_display, duration])
            item.setData(0, Qt.UserRole, session)
            self.sessions_tree.addTopLevelItem(item)

    def _add_session(self):
        """新增工時記錄"""
        dialog = SingleSessionEditDialog(self.date_str, parent=self)
        if dialog.exec() == QDialog.Accepted:
            new_session = dialog.get_session()
            self.sessions.append(new_session)
            self._load_sessions()

    def _edit_session(self):
        """編輯選中的工時記錄"""
        selected_items = self.sessions_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "請選擇要編輯的記錄")
            return

        item = selected_items[0]
        session = item.data(0, Qt.UserRole)
        index = self.sessions.index(session)

        dialog = SingleSessionEditDialog(self.date_str, session, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.sessions[index] = dialog.get_session()
            self._load_sessions()

    def _delete_session(self):
        """刪除選中的工時記錄"""
        selected_items = self.sessions_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "請選擇要刪除的記錄")
            return

        reply = QMessageBox.question(
            self, "確認刪除",
            "確定要刪除選中的工時記錄嗎？",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            item = selected_items[0]
            session = item.data(0, Qt.UserRole)
            self.sessions.remove(session)
            self._load_sessions()

    def _on_save_clicked(self):
        """儲存按鈕點擊事件"""
        self.accept()

    def get_sessions(self):
        """獲取編輯後的工時記錄"""
        return self.sessions

    def closeEvent(self, event):
        self.data_manager.save_window_geometry("work_session_edit_dialog", self)
        super().closeEvent(event)

class SingleSessionEditDialog(QDialog):
    """單個工時記錄編輯對話框"""
    def __init__(self, date_str, session=None, parent=None):
        super().__init__(parent)
        self.date_str = date_str
        self.session = session
        self.setWindowTitle("編輯工時記錄" if session else "新增工時記錄")
        self.setMinimumSize(400, 200)
        self._build_ui()
        if self.session:
            self._load_session_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 開始時間
        start_row = QWidget()
        start_layout = QHBoxLayout(start_row)
        start_layout.setContentsMargins(0, 0, 0, 0)
        start_layout.addWidget(QLabel("開始時間:"))
        self.start_datetime = QDateTimeEdit(QDateTime.currentDateTime())
        self.start_datetime.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_datetime.setCalendarPopup(True)
        start_layout.addWidget(self.start_datetime, 1)
        layout.addWidget(start_row)

        # 結束時間
        end_row = QWidget()
        end_layout = QHBoxLayout(end_row)
        end_layout.setContentsMargins(0, 0, 0, 0)
        end_layout.addWidget(QLabel("結束時間:"))
        self.end_datetime = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_datetime.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.end_datetime.setCalendarPopup(True)
        end_layout.addWidget(self.end_datetime, 1)
        layout.addWidget(end_row)

        layout.addStretch()

        # 按鈕
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        save_btn = QPushButton("儲存")
        save_btn.setMinimumWidth(100)
        save_btn.clicked.connect(self._on_save_clicked)
        cancel_btn = QPushButton("取消")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def _load_session_data(self):
        """載入工時記錄到表單"""
        start = self.session.get('start', '')
        end = self.session.get('end', '')

        if start:
            try:
                start_dt = datetime.fromisoformat(start)
                self.start_datetime.setDateTime(QDateTime(
                    QDate(start_dt.year, start_dt.month, start_dt.day),
                    QTime(start_dt.hour, start_dt.minute, start_dt.second)
                ))
            except Exception:
                pass

        if end:
            try:
                end_dt = datetime.fromisoformat(end)
                self.end_datetime.setDateTime(QDateTime(
                    QDate(end_dt.year, end_dt.month, end_dt.day),
                    QTime(end_dt.hour, end_dt.minute, end_dt.second)
                ))
            except Exception:
                pass

    def _on_save_clicked(self):
        """儲存按鈕點擊事件"""
        start_qdt = self.start_datetime.dateTime()
        end_qdt = self.end_datetime.dateTime()

        if start_qdt >= end_qdt:
            QMessageBox.warning(self, "警告", "結束時間必須晚於開始時間！")
            return

        self.accept()

    def get_session(self):
        """獲取編輯後的工時記錄"""
        start_qdt = self.start_datetime.dateTime()
        end_qdt = self.end_datetime.dateTime()

        start_dt = datetime(
            start_qdt.date().year(),
            start_qdt.date().month(),
            start_qdt.date().day(),
            start_qdt.time().hour(),
            start_qdt.time().minute(),
            start_qdt.time().second()
        )

        end_dt = datetime(
            end_qdt.date().year(),
            end_qdt.date().month(),
            end_qdt.date().day(),
            end_qdt.time().hour(),
            end_qdt.time().minute(),
            end_qdt.time().second()
        )

        return {
            'start': start_dt.isoformat(),
            'end': end_dt.isoformat()
        }
