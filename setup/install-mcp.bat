@echo off
setlocal
cd /d "%~dp0.."
call "%~dp0install.bat" mcp
if errorlevel 1 goto :fail
echo Installing optional Blow AI MCP support...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-mcp.txt
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -B setup\mcp_config.py --output mcp-config.local.json
if errorlevel 1 goto :fail
echo.
echo MCP support installed. Start ui.bat, then copy mcp-config.local.json into your MCP client's server settings.
echo Normal UI use still starts with ui.bat. Do not double-click mcp.bat to open the UI.
if "%~1"=="" pause
exit /b 0
:fail
echo MCP setup failed. Review the message above.
if "%~1"=="" pause
exit /b 1
