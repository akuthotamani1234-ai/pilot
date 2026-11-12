@echo off
REM The installer. Double-click it to install everything the tester needs (ui.bat and run.bat also call it before
REM every start, so double-clicking them is enough too). Whatever is missing is installed, whatever is there is only
REM checked (about 2 seconds), so it is safe to run at any time:
REM   1. Python 3.13 + .venv  (Python is installed by the Python install manager or winget if it is missing)
REM   2. the packages         (again when requirements.txt / constraints.txt changed or a package is missing)
REM   3. the Chromium browser (downloaded only when it is missing)
REM   4. .env                 (copied from .env.example the first time)
REM Double-clicked by itself (ui.bat / run.bat pass an argument), it waits for a key at the end so you can read it.
setlocal
REM everything is installed in the project folder (one level up from this setup folder)
cd /d "%~dp0.."
REM Python 3.13 is the tested version; 3.14 also installs the packages. 3.15 can't yet: PyYAML (needed by
REM langgraph) has no ready-made Windows package for it, and building one needs a C compiler.
set "SUPPORTED=import sys; sys.exit(0 if sys.version_info[:2] in ((3, 13), (3, 14)) else 1)"
REM every package pinned in requirements.txt is installed at that version (read from the package list, nothing imported)
set "PINNED=import sys, importlib.metadata as m; r = [l.split('#')[0].split('==') for l in open('requirements.txt')]; sys.exit(any(m.version(x[0].strip()) != x[1].strip() for x in r if len(x) == 2))"

REM ---- 1. Python + .venv
REM A .venv copied from another PC (the folder was zipped / copied with it) points to THAT PC's Python and can't start
REM here, and one made with an unsupported Python can't install the packages: either one is made again
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -c "%SUPPORTED%" >nul 2>&1 || (
        echo The .venv folder was made on another PC or with another Python version - making it again...
        rmdir /s /q .venv
    )
)
if exist .venv\Scripts\python.exe goto :packages
call :find_python || goto :fail
echo First-time setup with %PYTHON%: creating .venv and installing packages. This takes a few minutes...
%PYTHON% -m venv .venv
if not exist .venv\Scripts\python.exe (
    echo Could not create .venv with %PYTHON%.
    goto :fail
)
.venv\Scripts\python.exe -m pip install --upgrade pip

:packages
REM ---- 2. Packages: .venv\requirements.installed / constraints.installed = the files that were installed last
fc /b requirements.txt .venv\requirements.installed >nul 2>&1 || goto :install
fc /b constraints.txt .venv\constraints.installed >nul 2>&1 || goto :install
.venv\Scripts\python.exe -c "%PINNED%" >nul 2>&1 && goto :browser
echo A package of the tester is missing or has another version - installing again...
:install
echo Installing the packages of requirements.txt ...
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :fail
copy /y requirements.txt .venv\requirements.installed >nul
copy /y constraints.txt .venv\constraints.installed >nul

:browser
REM ---- 3. The Chromium browser: Playwright downloads it only when it is missing (no internet needed when it is there)
.venv\Scripts\python.exe -m playwright install chromium || goto :fail

REM ---- 4. Settings
if not exist .env copy .env.example .env >nul
if "%~1"=="" (
    echo.
    echo Setup is done: everything is installed. Double-click ui.bat to start the tester.
    pause
)
exit /b 0

:fail
echo.
echo Setup did not finish - see the message above. Fix it, then double-click ui.bat again.
if "%~1"=="" pause
exit /b 1

:find_python
REM Sets PYTHON to a supported Python, in this order: an installed 3.13; 3.13 installed by the Python install manager
REM (the `py` command of python.org's installer since 2025); an installed 3.14; 3.13 installed by winget (part of
REM Windows 10 / 11) for this Windows user only. Never 3.15 (see SUPPORTED).
py -3.13 -c "%SUPPORTED%" >nul 2>&1 && (set "PYTHON=py -3.13" & exit /b 0)
py list >nul 2>&1 && (
    echo Python 3.13 is not installed - installing it with the Python install manager, once. This takes a minute...
    py install -y 3.13
)
py -3.13 -c "%SUPPORTED%" >nul 2>&1 && (set "PYTHON=py -3.13" & exit /b 0)
py -3.14 -c "%SUPPORTED%" >nul 2>&1 && (set "PYTHON=py -3.14" & exit /b 0)
python -c "%SUPPORTED%" >nul 2>&1 && (set "PYTHON=python" & exit /b 0)
call :python_path && exit /b 0
winget --version >nul 2>&1 && (
    echo Python 3.13 is not installed - installing it with winget, once. This takes a few minutes...
    winget install --id Python.Python.3.13 --exact --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
)
call :python_path && exit /b 0
echo Python 3.13 was not found and could not be installed. Install Python 3.13 from
echo https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH"), then double-click ui.bat again.
echo Python 3.15 can't install the packages yet.
exit /b 1

:python_path
REM A Python 3.13 that was just installed is not on this window's PATH yet: look where the installers put it
for %%P in ("%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%LOCALAPPDATA%\Python\pythoncore-3.13-64\python.exe") do (
    if exist %%P %%P -c "%SUPPORTED%" >nul 2>&1 && (set "PYTHON="%%~P"" & exit /b 0)
)
exit /b 1
