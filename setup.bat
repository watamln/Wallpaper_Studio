@echo off
REM ------------------------------------------------------------------
REM  Wallpaper Studio - optional source setup for Windows 11
REM  (You do NOT need this to run the .exe from Releases!)
REM  Requires: Python 3.10+ (https://python.org - tick "Add to PATH")
REM ------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)

echo Checking Python...
%PY% --version || (echo Please install Python from python.org & pause & exit /b 1)

echo Creating virtual environment...
%PY% -m venv .venv

echo Installing dependencies (customtkinter, pillow)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" -m pip install -e .

echo.
echo Done! Launch with:  run.bat
pause
