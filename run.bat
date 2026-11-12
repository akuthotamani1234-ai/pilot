@echo off
REM Double-click this file: it starts the app (the web UI opens in your browser) - same as ui.bat.
REM Terminal version instead:  run.bat https://your-site.com   (tests that site right here, no web page)
cd /d "%~dp0"
REM no __pycache__ folders in the project (Python's compiled copies of the code: not needed, it reads the code itself)
set PYTHONDONTWRITEBYTECODE=1
if "%~1"=="" (
    call "%~dp0ui.bat"
    exit /b
)
REM install whatever is missing (the first time: everything), then start
call "%~dp0setup\install.bat" run || (pause & exit /b 1)
.venv\Scripts\python.exe main.py %*
echo.
pause
