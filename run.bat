@echo off
REM Launch Wallpaper Studio from source. Run setup.bat first.
REM (If you downloaded WallpaperStudio.exe from Releases, you don't need this.)
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Virtual env missing - run setup.bat first.
    pause & exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m wallpaper_studio.app
endlocal
