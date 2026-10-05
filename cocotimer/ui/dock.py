"""側邊停靠模式：主視窗收進螢幕邊緣的半透明小把手，點一下就從側邊滑出來。

- 把手貼在指定螢幕的左邊或右邊（只用工作列以外的空間），可以上下拖動，位置會記住。
- 主視窗滑出時蓋在其他視窗上面（不會把其他視窗擠開），點到別的程式就自動收回；按釘選就不收回。
- 用「滑鼠停在把手上就展開」打開時，Windows 不允許程式自己搶焦點，所以另外留意視窗外的點擊來收回。
- 前景是全螢幕程式時，把手會暫時讓位。
- 一般模式的視窗位置另外保存，回到一般模式時恢復原狀。
"""
import sys

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from cocotimer.ui.topmost import fullscreen_on_same_monitor

HANDLE_W, HANDLE_H = 16, 104
SLIDE = 56          # 滑動的距離（像素）
DURATION = 220      # 動畫長度（毫秒）
HOVER_DELAY = 280   # 「滑鼠停留就展開」要停多久
POLL_MS = 1500      # 檢查全螢幕程式、工作列或螢幕變動的間隔
OUTSIDE_MS = 60     # 沒有焦點時，檢查視窗外點擊的間隔
PANEL_FLAGS = Qt.Window | Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint


# --- 位置計算（不需要視窗，方便測試） ---

def dock_width(avail: QRect, percent: int, minimum: int = 420) -> int:
    """停靠時的寬度：螢幕可用寬度的百分比，但不小於 minimum（主視窗的最小寬度）。"""
    return max(minimum, round(avail.width() * max(1, percent) / 100))


def panel_rect(avail: QRect, side: str, width: int) -> QRect:
    w = max(1, min(width, avail.width()))
    x = avail.left() if side == "left" else avail.right() - w + 1
    return QRect(x, avail.top(), w, avail.height())


def handle_rect(avail: QRect, side: str, pos: float, w: int = HANDLE_W, h: int = HANDLE_H) -> QRect:
    pos = min(1.0, max(0.0, pos))
    y = avail.top() + round(pos * max(0, avail.height() - h))
    x = avail.left() if side == "left" else avail.right() - w + 1
    return QRect(x, y, w, h)


def handle_pos(avail: QRect, top: int, h: int = HANDLE_H) -> float:
    room = avail.height() - h
    return 0.5 if room <= 0 else min(1.0, max(0.0, (top - avail.top()) / room))


def _win_mouse_down():
    """Windows：滑鼠左鍵或右鍵是否按著（包含上次檢查後按過又放開的）。"""
    import ctypes
    state = ctypes.windll.user32.GetAsyncKeyState
    state.restype = ctypes.c_short
    return bool(state(0x01) & 0x8001 or state(0x02) & 0x8001)


def _win_foreground_is_ours():
    """Windows：目前最前面（有焦點）的視窗是不是 CocoTimer 自己的。
    直接問 Windows，不看 Qt 的 applicationState：用滑鼠停留展開時，Qt 可能以為自己有焦點，其實沒有。"""
    import ctypes
    import os
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def find_screen(name: str):
    for screen in QGuiApplication.screens():
        if name and screen.name() == name:
            return screen
    return QGuiApplication.primaryScreen()


def screen_label(index: int, screen) -> str:
    size = screen.size()
    primary = "，主螢幕" if screen == QGuiApplication.primaryScreen() else ""
    return f"螢幕 {index + 1}（{size.width()}×{size.height()}{primary}）"


class DockHandle(QWidget):
    """貼在螢幕邊緣的小把手：點一下展開、上下拖動換位置、右鍵有選單。番茄鐘進行中時會亮一個小圓點。"""

    def __init__(self, controller):
        super().__init__(None)
        self.controller = controller
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(HANDLE_W, HANDLE_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("CocoTimer：點一下展開，可以上下拖動，右鍵有更多選項")
        self.setAccessibleName("展開 CocoTimer")
        self.side = "right"
        self.status_color = None
        self.hovered = False
        self._press = None
        self._dragging = False
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(HOVER_DELAY)
        self.hover_timer.timeout.connect(controller.slide_in)

    def set_status(self, color):
        if color != self.status_color:
            self.status_color = color
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        radius = r.width() * 0.75
        # 只有朝向螢幕內側的那一邊是圓角
        body = r.adjusted(0, 0, radius, 0) if self.side == "right" else r.adjusted(-radius, 0, 0, 0)
        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)
        p.setClipRect(r)
        p.fillPath(path, QColor(36, 28, 23, 215 if self.hovered else 140))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawPath(path)
        # 箭頭（指向螢幕內側）
        cx, cy = r.center().x(), r.center().y()
        d = 2.5 if self.side == "right" else -2.5  # 停在右邊時箭頭朝左
        p.setPen(QPen(QColor(255, 255, 255, 230 if self.hovered else 170), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPointF(cx + d, cy - 5), QPointF(cx - d, cy), QPointF(cx + d, cy + 5)])
        if self.status_color:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self.status_color))
            p.drawEllipse(QPointF(cx, r.top() + 14), 3.2, 3.2)

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        if self.controller.open_on_hover():
            self.hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.hover_timer.stop()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = (event.globalPosition().toPoint().y(), self.y())
            self._dragging = False
            self.hover_timer.stop()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is not None:
            dy = event.globalPosition().toPoint().y() - self._press[0]
            if abs(dy) > 4:
                self._dragging = True
            if self._dragging:
                avail = self.controller.available()
                top = min(max(avail.top(), self._press[1] + dy), avail.bottom() - self.height() + 1)
                self.move(self.x(), top)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._press is not None:
            if self._dragging:
                self.controller.handle_moved(self.y())
            else:
                self.controller.toggle()
        self._press = None
        self._dragging = False
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.controller.show_menu(event.globalPos())


class DockController(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.active = False
        self.is_open = False
        self.pinned = False
        self.handle = None
        self.anim = None
        self._avail = QRect()
        self._yielded = False
        self.poll = QTimer(self)
        self.poll.setInterval(POLL_MS)
        self.poll.timeout.connect(self._poll)
        # 沒拿到焦點時（滑鼠停留展開），改成留意視窗外的點擊；只在這種時候才檢查，平常不耗資源
        self.outside = QTimer(self)
        self.outside.setInterval(OUTSIDE_MS)
        self.outside.timeout.connect(self._check_outside_click)
        self._mouse_down = _win_mouse_down if sys.platform == "win32" else None
        self._foreground_is_ours = (_win_foreground_is_ours if sys.platform == "win32"
                                    else lambda: QGuiApplication.applicationState() == Qt.ApplicationActive)
        self._cursor_pos = QCursor.pos
        QApplication.instance().applicationStateChanged.connect(self._on_app_state)

    # --- 設定 ---

    def settings(self):
        return self.mw.settings

    def side(self):
        return "left" if self.settings().dock_side == "left" else "right"

    def open_on_hover(self):
        return self.settings().dock_open_on_hover

    def available(self) -> QRect:
        return find_screen(self.settings().dock_screen).availableGeometry()

    def apply_settings(self):
        """依照設定進入、離開或重新排列停靠模式。"""
        enabled = self.settings().dock_enabled
        if enabled and not self.active:
            self.enter()
            self.slide_in()  # 剛切換過來時先展開一次，讓人看到它停在哪裡
        elif not enabled and self.active:
            self.exit()
        elif self.active:
            self.reposition()

    # --- 進入／離開 ---

    def enter(self):
        if self.active:
            return
        mw = self.mw
        mw.data_manager.save_window_geometry("main_window", mw)  # 先記下一般模式的位置
        mw._cocotimer_geometry_paused = True
        mw.hide()
        mw.setWindowFlags(PANEL_FLAGS)
        self.active, self.is_open, self.pinned = True, False, False
        self.handle = DockHandle(self)
        self.reposition()
        self.handle.show()
        self.poll.start()
        mw.sidebar.set_dock_mode(True, self.pinned, self.side())
        mw._layout_shell()

    def exit(self):
        if not self.active:
            return
        mw = self.mw
        self._stop_animation()
        self.poll.stop()
        self.outside.stop()
        if self.handle is not None:
            self.handle.hide()
            self.handle.deleteLater()
            self.handle = None
        mw.hide()
        mw.clearMask()
        mw.setWindowOpacity(1.0)
        mw.setWindowFlags(Qt.Window)
        self.active = self.is_open = self.pinned = False
        mw._cocotimer_geometry_paused = False
        mw.data_manager.restore_window_geometry("main_window", mw)
        mw.sidebar.set_dock_mode(False, False, self.side())
        mw._layout_shell()
        mw.show()
        mw.raise_()
        mw.activateWindow()

    def reposition(self):
        if not self.active:
            return
        self._avail = self.available()
        side = self.side()
        self.handle.side = side
        self.handle.setGeometry(handle_rect(self._avail, side, self.settings().dock_handle_pos))
        self.handle.update()
        if self.is_open and self.anim is None:
            self.mw.setGeometry(self.target())
        self.mw.sidebar.set_dock_mode(True, self.pinned, side)
        self.mw._layout_shell()

    def target(self) -> QRect:
        return panel_rect(self._avail, self.side(), dock_width(self._avail, self.settings().dock_width_percent, self.mw.minimumWidth()))

    # --- 滑出／收回 ---

    def toggle(self):
        if self.is_open:
            self.slide_out()
        else:
            self.slide_in()

    def slide_in(self):
        if not self.active:
            return
        mw = self.mw
        if self.is_open and self.anim is None:
            mw.raise_()
            mw.activateWindow()
            return
        self._avail = self.available()
        target = self.target()
        start = target.topLeft() + QPoint(SLIDE if self.side() == "right" else -SLIDE, 0)
        if not self.is_open:
            mw.setGeometry(target)  # 先排好版面再顯示
            mw.move(start)
            mw.setWindowOpacity(0.0)
        self.is_open = True
        if self.handle is not None:
            self.handle.hover_timer.stop()
            self.handle.hide()
        mw.show()
        mw.raise_()
        mw.activateWindow()
        self._animate(mw.pos(), target.topLeft(), mw.windowOpacity(), 1.0, QEasingCurve.OutCubic, self._finish_in)

    def slide_out(self):
        if not self.active or not self.is_open:
            return
        self.is_open = False
        self.outside.stop()
        mw = self.mw
        end = self.target().topLeft() + QPoint(SLIDE if self.side() == "right" else -SLIDE, 0)
        self._animate(mw.pos(), end, mw.windowOpacity(), 0.0, QEasingCurve.InCubic, self._finish_out)

    def _animate(self, start, end, op_from, op_to, curve, done):
        self._stop_animation()
        mw = self.mw
        avail = self._avail
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(DURATION)
        anim.setEasingCurve(curve)

        def step(t):
            pos = QPoint(round(start.x() + (end.x() - start.x()) * t), round(start.y() + (end.y() - start.y()) * t))
            mw.move(pos)
            mw.setWindowOpacity(op_from + (op_to - op_from) * t)
            # 只顯示在這個螢幕裡的部分，旁邊有其他螢幕時不會露出來
            mw.setMask(QRegion(QRect(avail.topLeft() - pos, avail.size())))

        anim.valueChanged.connect(step)
        anim.finished.connect(done)
        self.anim = anim
        anim.start()

    def _stop_animation(self):
        if self.anim is not None:
            self.anim.stop()
            self.anim.deleteLater()
            self.anim = None

    def _finish_in(self):
        self._stop_animation()
        self.mw.clearMask()
        self.mw.setWindowOpacity(1.0)
        self.mw.move(self.target().topLeft())
        if self._mouse_down is not None:
            self._mouse_down()  # 清掉展開前留下的「按過」紀錄
            self.outside.start()

    def _finish_out(self):
        self._stop_animation()
        mw = self.mw
        mw.hide()
        mw.clearMask()
        mw.setWindowOpacity(1.0)
        if self.handle is not None and not self._yielded:
            self.handle.show()

    # --- 自動收回、釘選、把手 ---

    def _on_app_state(self, state):
        if self.active and self.is_open and not self.pinned and state != Qt.ApplicationActive:
            QTimer.singleShot(150, self._retract_if_inactive)

    def _check_outside_click(self):
        """主視窗沒有焦點時，點到視窗外（其他程式或桌面）就收回。點到自己的懸浮工具或對話框不算。"""
        if not (self.active and self.is_open) or self._mouse_down is None:
            self.outside.stop()
            return
        if self.pinned or self._foreground_is_ours():
            return  # 真的有焦點時，點到別處會觸發 _on_app_state，交給它處理
        if not self._mouse_down():
            return
        pos = self._cursor_pos()
        if self.mw.frameGeometry().contains(pos) or QApplication.widgetAt(pos) is not None:
            return
        if QApplication.activeModalWidget() is None:
            self.slide_out()

    def _retract_if_inactive(self):
        if (self.active and self.is_open and not self.pinned
                and QGuiApplication.applicationState() != Qt.ApplicationActive
                and QApplication.activeModalWidget() is None):
            self.slide_out()

    def set_pinned(self, pinned):
        self.pinned = pinned
        self.mw.sidebar.set_dock_mode(True, pinned, self.side())

    def handle_moved(self, top):
        self.mw.update_settings(dock_handle_pos=round(handle_pos(self.available(), top), 4))

    def update_status(self, pomodoro_state):
        if self.handle is not None:
            colors = {"working": self.mw.colors["accent"], "breaking": "#2F8F5B"}
            self.handle.set_status(colors.get(pomodoro_state))

    def windows(self):
        """要保持在最上層的視窗。"""
        result = []
        if self.handle is not None and self.handle.isVisible():
            result.append(self.handle)
        if self.active and self.is_open:
            result.append(self.mw)
        return result

    def _poll(self):
        if not self.active or self.handle is None:
            return
        if self.available() != self._avail:
            self.reposition()  # 工作列移動、解析度改變或拔掉螢幕
        yielded = not self.is_open and fullscreen_on_same_monitor(self.handle)
        if yielded != self._yielded:
            self._yielded = yielded
            if not self.is_open:
                self.handle.setVisible(not yielded)

    def show_menu(self, pos):
        menu = QMenu()
        menu.addAction("展開 CocoTimer", self.slide_in)
        menu.addSeparator()
        side = self.side()
        for key, text in (("right", "停在右邊"), ("left", "停在左邊")):
            action = menu.addAction(text, lambda k=key: self._change(dock_side=k))
            action.setCheckable(True)
            action.setChecked(side == key)
        hover = menu.addAction("滑鼠停留就展開", lambda: self._change(dock_open_on_hover=not self.open_on_hover()))
        hover.setCheckable(True)
        hover.setChecked(self.open_on_hover())
        screens = QGuiApplication.screens()
        if len(screens) > 1:
            sub = menu.addMenu("停在哪個螢幕")
            current = find_screen(self.settings().dock_screen)
            for i, screen in enumerate(screens):
                action = sub.addAction(screen_label(i, screen), lambda n=screen.name(): self._change(dock_screen=n))
                action.setCheckable(True)
                action.setChecked(screen == current)
        menu.addSeparator()
        menu.addAction("回到一般視窗", lambda: self.mw.set_dock_enabled(False))
        menu.addAction("結束 CocoTimer", self.mw.quit_app)
        menu.exec(pos)

    def _change(self, **changes):
        self.mw.update_settings(**changes)
        self.reposition()
        self.mw.sync_settings_page()
