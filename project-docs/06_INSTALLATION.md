<div style="font-family: 'Segoe UI', Inter, system-ui, -apple-system, Roboto, Arial, sans-serif; line-height: 1.6;">

# 🧰 Installation Guide

### Blow AI – What to Install and How to Run It

| **Version** | 1.0 |
|---|---|
| **Date** | Oct 23, 2026 (checked against the code Nov 4, 2026) |
| **Platform** | Windows 10 / 11 (the sandbox and the account store are Windows-only; tested on Windows 11) |
| **Setup time** | about 5–10 minutes the first time (downloads packages and Chromium) |

---

## 1. Required Software

- **Windows 10 / 11**
  - the `.bat` launchers are for Windows
- **Python 3.13** (recommended – the tested version; 3.14 also works, 3.15 can't install the packages yet)
  - runs the backend, the agents and the generated tests
  - if it is missing, the installer installs it by itself (Python install manager `py`, or winget); by hand:
    download from python.org and tick **"Add python.exe to PATH"**
- **Python packages** (see section 2)
  - installed automatically into `.venv` by `ui.bat`
- **Chromium for Playwright**
  - the browser that crawls and tests
  - installed automatically by `ui.bat`
- **Internet connection**
  - for the first install, cloud AI and testing online websites

## 2. Python Packages (`requirements.txt`)

Pinned to the versions the full test suite passed with (updated Nov 2, 2026):
- **playwright** 1.64.0 – browser automation
- **pytest** 9.1.1 – runs the generated tests
- **pytest-xdist** 3.8.0 – several browsers at once
- **langgraph** 1.2.15 + **langgraph-checkpoint-sqlite** 3.1.2 – agent pipeline, `--resume`
- **pydantic** 2.14.1 – checks the AI's answers
- **requests** 2.34.2 – website check, AI calls, GitHub
- **openpyxl** 3.1.5 – Excel file
- **fastapi** 0.143.1 – web server / API
- **uvicorn** 0.54.0 – runs the web server

For working on the tester itself, `requirements-dev.txt` adds **ruff** 0.14.10 (code checker), **vulture** 2.14
(finds unused code) and **httpx** 0.28.1 (the server tests).

## 3. Optional Software

### 3.1 Ollama – Local AI (Recommended)
- **Why:** the default AI – free, private, no data leaves your PC.
- **Without it:** the run uses built-in rules instead of AI.
- **Install:**
  1. Download from ollama.com
  2. Run `ollama pull llama3.1` (about 5 GB)
  3. Keep it running (`ollama serve`)

### 3.2 Cloud AI API Key
- **Why:** to use Gemini, OpenAI or Claude instead of Ollama.
- **How:**
  - paste it in the UI (used for one run only), **or**
  - put it in `.env`, e.g. `GEMINI_API_KEY=...`

### 3.3 Git
- **Why:** faster GitHub cloning, and `git pull` to update the tester.
- **Without it:** the repo is downloaded as a .zip.
- **Install:** from git-scm.com.

### 3.4 Node.js
- **Why:** only needed to test a Node / React / Vite / Next / Angular **repo or folder**.
- **Install:** from nodejs.org (the version that project needs).

### 3.5 GitHub Token
- **Why:** private repos, and "Apply fixes as a Pull Request".
- **Permissions:** Contents + Pull requests: write.
- **Where:** GitHub → Settings → Developer settings → Fine-grained tokens → `.env` `GITHUB_TOKEN=`

### 3.6 Native Android testing (optional)
- **JDK 17 or newer** (JDK 21 recommended), **Android SDK Platform-Tools**, Android command-line tools, and **Node.js 20.19+ (20.x), 22.12+ (22.x), or 24+; npm 10+**.
- A connected Android device with USB debugging enabled, or an emulator. Android Studio is optional.
- Appium Server and the UiAutomator2 driver. Blow AI uses the server only on `127.0.0.1`; it does not install or start global Node packages automatically.
- Emulator acceleration must be enabled in the PC firmware/Windows hypervisor. If it is unavailable, use an authorized physical device.

## 4. First-Time Setup

### 4.1 Easiest Way
Double-click **`ui.bat`**. It calls the installer `setup\install.bat` (which can also be double-clicked by itself),
which the first time:
1. installs Python 3.13 if it is missing, and creates `.venv`
2. installs `requirements.txt` at the versions of `constraints.txt`
3. installs Chromium
4. copies `.env.example` → `.env`

Then `ui.bat` starts the server and opens **http://127.0.0.1:8000**.

- Keep the black window open while you use the UI.
- Double-click again to restart with the latest code.
- Every start checks each part (about 2 seconds) and installs only what is missing: the packages when
  `requirements.txt` / `constraints.txt` changed or a package is missing, Chromium if it was deleted.

### 4.2 By Hand (PowerShell)
```powershell
cd blow-ai
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
copy .env.example .env
.venv\Scripts\python.exe -m backend.server
```
- Calling `.venv\Scripts\python.exe` directly needs no activation (so no `Set-ExecutionPolicy` change).

Installing on another PC, updating and what never to copy: see [../DEPLOYMENT.md](../DEPLOYMENT.md).

## 5. Settings (`.env`)

### 5.1 AI
- `LLM_PROVIDER` – `ollama` (default), `gemini`, `openai`, `anthropic` or `none`
- `LLM_MODEL` – e.g. `llama3.1`, `gemini-flash-latest`, `gpt-4o-mini`, `claude-sonnet-5-5`
- `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` – cloud AI keys
- `OLLAMA_URL` – default `http://localhost:11434`
- `LLM_TIMEOUT` – seconds to wait for one AI answer (default 240)
- `LLM_BUDGET_USD` – the most a run may spend on the AI (default 2); then the built-in rules are used
- `VISION` – the AI looks at screenshots: `auto` (default: with a cloud AI or an Ollama vision model), `on`, `off`
- `LLM_PRICE_INPUT_PER_M`, `LLM_PRICE_OUTPUT_PER_M` – your own prices for the cost report

### 5.2 Crawling and Testing
- `MAX_PAGES` / `MAX_DEPTH` – 0 means no per-run page/depth limit; the safety caps still apply
- `HARD_PAGE_CAP` / `CRAWL_TIME_LIMIT_MIN` – safety limits for a full crawl (500 pages / 30 minutes by default)
- `PATTERN_SAMPLES` – 0 visits every discovered route and listed item; set above 0 to inspect representative pages
  for repeated address patterns
- `CRAWL_SCOPE` – `auto` (default) decides from the link: entire website / limited pages / specific page;
  `site`, `section` or `page` forces one mode
- `HEADLESS` – `false` shows the browser (default `true`)
- `SLOW_MO_MS` – pause after each action (0; the UI uses 800 when you watch in Chrome)
- `TEST_ENVIRONMENT` – `test` (default), `staging` or `production` (README, Environments)
- `DATA_TESTS` / `DATA_MAX_FIELDS` – optional input-robustness checks (false / 4 boxes per page); core functional checks still run
- `TEST_RETRIES` – failed-test retries for flaky-test detection (0 by default; set to 1 to retry once)
- `TEST_WORKERS` – browsers in parallel (4)
- `MAX_HEAL_ROUNDS` – self-healing rounds (2)

### 5.3 Code Input
- `GITHUB_TOKEN` – private repos + Pull Requests
- `SERVER_START_TIMEOUT` – seconds to wait for the app to start (180)
- `START_CMD` / `APP_PORT` – override the start command / port

### 5.4 Read by the Code but Not in `.env.example`
- `RUNS_DIR`, `BASELINE_DIR`, `WORKSPACE_DIR`: other folders for a command-line run (the web UI always uses
  `runs/` and `baseline/` in the project folder).
- Every other setting, including `HARD_PAGE_CAP`, `PAGE_TIMEOUT_MS`, `HUMAN_WAIT_S` and `UI_PORT`, is in
  `.env.example` with its explanation.

## 6. Check That It Works

1. Double-click `ui.bat` → the page opens at http://127.0.0.1:8000.
2. Paste `https://the-internet.herokuapp.com`.
3. Choose **No AI** (fastest), pages = 5, press **Start testing**.
4. You should see the Excel, the live pass / fail list and the final report.
5. Optional (developers): `.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile -m "not slow"` → the quick
   tests pass (all tests and their times: [../tests/README.md](../tests/README.md)).

## 7. Common Problems

- **"Python 3.13 was not found"** → install Python 3.13 from python.org with "Add python.exe to PATH", then
  double-click `ui.bat` again.
- **Ollama shows "not running"** → start Ollama and run `ollama pull llama3.1`.
- **Gemini is slow / times out** → raise `LLM_TIMEOUT` or choose another engine.
- **Port 8000 is in use** → set `UI_PORT=8010` in `.env`.
- **Repo app doesn't start** → set `START_CMD`, e.g. `npm run dev -- --port {port}`.
- **Website blocks the crawler** → use your own, staging or practice site.

## 8. Native Android setup and use (optional)

The native Android path is separate from `backend/mobile.py`, which tests responsive website layouts in Playwright. The
Android path uses Appium + UiAutomator2 and requires an Android device or emulator.

On Windows, install a JDK 17+ and Android command-line tools for your user, then set `JAVA_HOME` and
`ANDROID_SDK_ROOT`. In PowerShell, install Appium in a user-local folder (not globally):

```powershell
$prefix = "$env:LOCALAPPDATA\BlowAI\AndroidTools"
npm install --prefix $prefix appium@3.9.0
$env:PATH += ";$prefix\node_modules\.bin"
appium driver install uiautomator2@8.7.3
```

Set `JAVA_HOME` to the JDK folder and `ANDROID_SDK_ROOT` to the SDK folder. Install SDK Platform-Tools, API 36,
Build-Tools and the emulator executable with `sdkmanager`:

```powershell
sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0" "emulator"
```

Add `platform-tools` to `PATH` and verify a device with `adb devices`. Start the server explicitly in a separate terminal:

```powershell
appium --address 127.0.0.1
```

In the UI choose **Test an Android app**, refresh device status, select an APK upload or an installed package, and
confirm authorization. Uploads are stored under the run's private folder and are not served as static files. The
APK is installed and executed on the selected device; upload only trusted apps and prefer a disposable emulator.
The pipeline explores/replays only visible, clearly navigational controls. It does not enter form data or perform payments,
deletes, account changes, uploads, or other consequential actions. Such controls are reported as blocked, so the
result is a bounded smoke assessment rather than full app certification.

The server does not install or start Appium for you. The UI shows missing prerequisites, including when no authorized
device is connected. If Appium cannot create a session, the report records an infrastructure problem instead of a pass.
Use Android Studio's Device Manager only when emulator acceleration is available; otherwise connect a device with USB
debugging enabled and approve its ADB prompt.

---

**Related documents:** [PRD](01_PRD.md) · [Architecture](02_ARCHITECTURE.md) · [Rules](03_RULES.md) ·
[Design](04_DESIGN.md) · [Execution Process](05_EXECUTION_PROCESS.md)

</div>

Detailed mobile architecture, AI behavior, contracts, checkpoint resume and verification: [Android guide](12_ANDROID.md).
