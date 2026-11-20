@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo Installing dependencies...
python -m pip install -r requirements.txt
echo.
echo Building ZapretGUI.exe ...
python -m PyInstaller ZapretGUI.spec --noconfirm
echo.
echo Done. EXE: %~dp0dist\ZapretGUI.exe
pause