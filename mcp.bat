@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Blow AI environment missing. Run setup\install-mcp.bat first. 1>&2
    exit /b 2
)
".venv\Scripts\python.exe" -u -B "%~dp0mcp_entry.py" %*
exit /b %errorlevel%
