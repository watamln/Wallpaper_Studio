@echo off
REM Launch Wallpaper Studio (GUI). Run setup.bat first.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Virtual env missing - run setup.bat first.
    pause & exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m wallpaper_studio.app
endlocal
