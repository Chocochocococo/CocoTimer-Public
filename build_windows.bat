@echo off
rem 在 Windows 上打包 CocoTimer：雙擊執行，或在命令提示字元輸入 build_windows.bat
rem 需要先安裝 Python 3.10 以上。完成後程式在 dist\CocoTimer\CocoTimer.exe
chcp 65001 > nul
python -m pip install --upgrade pip
rem 只裝需要的部分：PySide6-Essentials 比完整的 PySide6 小很多；openpyxl 是「匯出 Excel」用的（不裝會改存 CSV）
python -m pip install PySide6-Essentials zhdate openpyxl pyinstaller
python -m PyInstaller --noconfirm --clean CocoTimer.spec
if errorlevel 1 (
    echo 打包失敗，請把上面的訊息截圖給水豚君。
) else (
    copy /y LICENSE dist\CocoTimer\LICENSE.txt > nul
    echo 完成！程式在 dist\CocoTimer\ 資料夾裡。
)
pause
