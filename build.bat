@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 打包本地AI翻译助手.exe ...
pip install pyinstaller -q
pyinstaller --noconsole --onefile --collect-all tkinterdnd2 gui_translate.py
echo.
echo 完成！产物在 dist\本地AI翻译助手.exe
pause
