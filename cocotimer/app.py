import hashlib
import sys

from PySide6.QtCore import QLibraryInfo, Qt, QTimer, QTranslator
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QStyle, QSystemTrayIcon

from cocotimer.data_manager import DataManager
from cocotimer.paths import DATA_DIR, resource_path
from cocotimer.ui.main_window import MainWindow
from cocotimer.ui.tray import SystemTrayIcon


def instance_name() -> str:
    """同一個資料夾只允許開一個 CocoTimer；不同資料夾的可攜版可以同時執行。"""
    return "CocoTimer-" + hashlib.sha1(DATA_DIR.lower().encode("utf-8")).hexdigest()[:12]


def notify_running_instance() -> bool:
    """如果已經有 CocoTimer 在執行，請它把主視窗叫出來，回傳 True。"""
    socket = QLocalSocket()
    socket.connectToServer(instance_name())
    if not socket.waitForConnected(300):
        return False
    socket.write(b"show")
    socket.flush()
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


class TimeManagerApp(QApplication):
    def __init__(self, argv, start=True):
        super().__init__(argv)
        self.setStyle("Fusion")
        self.setQuitOnLastWindowClosed(False)
        # Qt 內建對話框（是／否、選擇檔案、顏色、字體）用繁體中文
        self.qt_translator = QTranslator(self)
        if self.qt_translator.load("qtbase_zh_TW", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            self.installTranslator(self.qt_translator)
        self.main_window = None
        self.server = None
        if start:
            self.start()

    def start(self):
        self.data_manager = DataManager()
        theme = self.data_manager.load_settings().theme
        self.setFont(QFont(theme.font_family))

        icon = QIcon(resource_path("icon.ico"))
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.setWindowIcon(icon)

        self.tray_icon = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = SystemTrayIcon(icon, None, self)
            self.tray_icon.show()

        self.main_window = MainWindow(tray_icon=self.tray_icon)
        self._listen_for_other_instances()

        # 登出或關機時，視窗不一定會收到關閉事件，所以在這裡另外存檔
        self.commitDataRequest.connect(lambda _manager: self.main_window.save_session_state())
        self.aboutToQuit.connect(self.data_manager.flush)

        if self.tray_icon:
            self.tray_icon.main_window = self.main_window
            self.tray_icon.showMessage("CocoTimer", "程式已在系統托盤中運行", QSystemTrayIcon.Information, 3000)
        self.main_window.show_on_start()
        self._report_data_problems()
        QTimer.singleShot(400, self.main_window.maybe_show_welcome)

    def _listen_for_other_instances(self):
        name = instance_name()
        QLocalServer.removeServer(name)  # 清掉上次異常結束留下的殘骸
        self.server = QLocalServer(self)
        if self.server.listen(name):
            self.server.newConnection.connect(self._on_other_instance)

    def _on_other_instance(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: s.readAll())
            socket.disconnected.connect(socket.deleteLater)
        if self.main_window:
            self.main_window.restore_from_tray()

    def _report_data_problems(self):
        if self.data_manager.problems:
            QMessageBox.warning(self.main_window, "資料檔提醒",
                                "\n\n".join(self.data_manager.problems)
                                + "\n\n每日備份放在 timemanager_data/backups 資料夾。")


def main():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = TimeManagerApp(sys.argv, start=False)
    if notify_running_instance():
        return
    app.start()
    sys.exit(app.exec())
