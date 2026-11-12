@echo off
REM Double-click this file: it starts the web UI and opens it in your browser.
REM Keep this window open while you use the UI - closing it stops the UI.
REM If an older UI window is still open, this one replaces it (so you always get the latest version).
cd /d "%~dp0"
REM no __pycache__ folders in the project (Python's compiled copies of the code: not needed, it reads the code itself)
set PYTHONDONTWRITEBYTECODE=1
REM install whatever is missing (the first time: everything), then start
call "%~dp0setup\install.bat" ui || (pause & exit /b 1)
.venv\Scripts\python.exe -m backend.server
REM Exit code 3 = a newer ui.bat took over: close this old window without waiting for a key press
if %errorlevel%==3 exit
echo.
pause
