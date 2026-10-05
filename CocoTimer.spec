# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包設定：pyinstaller CocoTimer.spec
# 輸出 dist/CocoTimer/（一個資料夾，裡面有 CocoTimer.exe）。資料會存在 exe 旁邊的 timemanager_data/，
# 整個資料夾壓縮起來就能帶著走。用資料夾而不是單一 exe：啟動比較快，也不用每次解壓縮到暫存區。
import os

# 用不到的 Qt 模組與 Python 套件（縮小體積、減少記憶體）
EXCLUDES = [
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuickWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.Qt3DCore", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSerialPort", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus",
    "tkinter", "unittest", "pydoc", "doctest", "lib2to3", "xmlrpc", "pytest",
]
# 打包工具有時還是會把這些 Qt 元件帶進來，最後再濾掉一次（檔名包含就排除）
DROP_FILES = [
    "opengl32sw", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "Qt6Multimedia", "Qt6OpenGL",
    "Qt6WebEngine", "Qt6Charts", "Qt6Sql", "Qt6Test", "Qt6Designer", "Qt6Help", "Qt6Bluetooth", "Qt6Positioning",
    "avcodec", "avformat", "avutil", "swresample", "swscale",
    os.path.join("plugins", "multimedia"), os.path.join("plugins", "qmltooling"), os.path.join("plugins", "tls"),
    os.path.join("plugins", "networkinformation"), os.path.join("plugins", "sqldrivers"),
    os.path.join("plugins", "virtualkeyboard"), os.path.join("plugins", "position"),
]


def keep_file(entry):
    name = entry[0].replace("/", os.sep)
    if any(part.lower() in name.lower() for part in DROP_FILES):
        return False
    # Qt 翻譯檔只留繁體中文（對話框的「是／否」等按鈕）
    if f"{os.sep}translations{os.sep}" in name and name.endswith(".qm"):
        return "zh_TW" in name and os.path.basename(name).startswith(("qt_", "qtbase_"))
    return True


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("sounds/water_alert.wav", "sounds"), ("sounds/pomodoro_alert.wav", "sounds"), ("icon.ico", ".")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
a.binaries = [b for b in a.binaries if keep_file(b)]
a.datas = [d for d in a.datas if keep_file(d)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CocoTimer",
    icon="icon.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CocoTimer")
