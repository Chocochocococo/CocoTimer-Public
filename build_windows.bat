@echo off
rem 在 Windows 上打包 CocoTimer：雙擊執行，或在命令提示字元輸入 build_windows.bat
rem 需要先安裝最新的 Python 3.14（python.org）。完成後程式在 dist\CocoTimer\CocoTimer.exe
chcp 65001 > nul
cd /d "%~dp0"
python --version || goto fail

rem 每次都在全新的虛擬環境裡打包：電腦上另外裝的套件（例如 Pillow、numpy）不會被夾帶進去，
rem 用到的套件也一定是最新版（裡面有最新的安全性修正）
if exist .build-venv rmdir /s /q .build-venv
python -m venv .build-venv || goto fail
set PY=.build-venv\Scripts\python.exe
%PY% -m pip install --upgrade pip || goto fail
rem 只裝需要的部分：PySide6-Essentials 比完整的 PySide6 小很多；openpyxl 是「匯出 Excel」用的（不裝會改存 CSV）
%PY% -m pip install --upgrade "PySide6-Essentials>=6.12.0" "openpyxl>=3.1.5" "pyinstaller>=6.22.1" zhdate || goto fail
%PY% -m PyInstaller --noconfirm --clean CocoTimer.spec || goto fail
copy /y LICENSE dist\CocoTimer\LICENSE.txt > nul
echo 完成！程式在 dist\CocoTimer\ 資料夾裡。
goto end

:fail
echo 打包失敗，請把上面的訊息截圖給水豚君。

:end
pause
