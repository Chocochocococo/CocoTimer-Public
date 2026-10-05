"""播放提醒音。

Windows 用系統內建的播放功能（winsound），不需要 Qt 的多媒體元件，打包後的程式小很多；
其他系統用 Qt 的 QSoundEffect；兩者都沒有時改用系統提示音，不會讓程式出錯。
"""
import sys

from PySide6.QtCore import QObject, QUrl
from PySide6.QtWidgets import QApplication

from cocotimer import sounds

USE_WINSOUND = sys.platform == "win32"


class SoundPlayer(QObject):
    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.paths = {}
        self.volume = 0.8
        self.effects = {}
        self._qt_effect = None
        if not USE_WINSOUND:
            try:
                from PySide6.QtMultimedia import QSoundEffect  # 只在非 Windows 載入
                self._qt_effect = QSoundEffect
            except ImportError:
                self._qt_effect = None
        self.reload()

    def reload(self):
        """設定改變（換音效、調音量）後重新載入。"""
        settings = self.data_manager.load_settings()
        self.volume = settings.volume
        for kind, (_name, _default, field) in sounds.KINDS.items():
            path = sounds.sound_path(kind, getattr(settings, field, ""), self.data_manager.data_dir)
            self.paths[kind] = path
            if USE_WINSOUND:
                sounds.volume_adjusted(path, self.volume)  # 先準備好，提醒響起時不用等
            if self._qt_effect is not None:
                effect = self.effects.get(kind) or self._qt_effect(self)
                if effect.source() != QUrl.fromLocalFile(path):
                    effect.setSource(QUrl.fromLocalFile(path))
                effect.setVolume(self.volume)
                self.effects[kind] = effect

    def play(self, kind):
        if USE_WINSOUND:
            try:
                import winsound
                path = sounds.volume_adjusted(self.paths[kind], self.volume)
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                return
            except (ImportError, RuntimeError, KeyError):
                pass
        effect = self.effects.get(kind)
        if effect is None:
            QApplication.beep()
            return
        effect.stop()
        effect.play()
