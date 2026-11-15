@echo off
cd /d "%~dp0"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" main.py
) else (
    python main.py
)
if %errorlevel% neq 0 (
    echo [ERROR] Application exited with code %errorlevel%
    pause
)
