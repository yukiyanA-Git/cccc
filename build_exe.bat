@echo off
cd /d "%~dp0"
echo Building standalone executable for CCCC...
if exist "%LOCALAPPDATA%\Programs\Python\Python311\Scripts\pyinstaller.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python311\Scripts\pyinstaller.exe" --noconfirm --onedir --windowed --name "CCCC" --icon "assets\cccc_icon.ico" --add-data "assets;assets" main.py
) else (
    pyinstaller --noconfirm --onedir --windowed --name "CCCC" --icon "assets\cccc_icon.ico" --add-data "assets;assets" main.py
)
echo.
echo Build completed! Check "dist\CCCC\CCCC.exe".
pause
