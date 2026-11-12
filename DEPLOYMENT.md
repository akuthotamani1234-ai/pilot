# Deploying Blow AI

This guide is for whoever installs Blow AI on a tester's PC or updates it there.

## How it is deployed
Each tester runs **their own copy on their own Windows PC**. The web UI only answers on that PC
(http://127.0.0.1:8000), so nobody else on the network can start, stop or read tests. To deploy, you copy the project
folder to the PC and double-click `ui.bat`. Nothing has to be built.

A shared server or a Docker container is **not supported in this version**. See
[Not supported yet](#not-supported-yet-a-shared-server-or-docker).

## 1. Get a clean copy
**From git (recommended):** `git clone <repository-url> blow-ai`. The repository never holds a tester's data or
secrets: `.gitignore` keeps out everything in the right-hand column below. Before the first push of a new
repository, check with `git status` that no `.env`, `accounts/`, `runs/` or `logs/` is listed.

**Without git:** copy the code and the documents. **Never copy a tester's local data or secrets.**

| Copy | Never copy |
|---|---|
| `backend/`, `frontend/`, `tests/`, `project-docs/` | `.env` (API keys, test accounts) |
| `main.py`, `setup/`, `ui.bat`, `run.bat` | `.venv/` (built for one PC; `setup\install.bat` creates a new one) |
| `requirements.txt`, `constraints.txt`, `requirements-dev.txt`, `pyproject.toml`, `pytest.ini` | `runs/`, `baseline/`, `logs/`, `workspace/`, `schedules.json` (one tester's runs and data) |
| `.env.example`, `.gitignore`, `.gitattributes`, `.editorconfig`, `.github/` | `accounts/` (encrypted for one Windows user, useless anywhere else) |
| `README.md`, `DEPLOYMENT.md`, `CONTRIBUTING.md`, `SECURITY.md` | `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` (caches) |

One command that makes such a copy (change both paths):
```powershell
robocopy C:\path\to\blow-ai D:\release\blow-ai /E /XD .venv runs baseline logs workspace accounts __pycache__ .pytest_cache .ruff_cache /XF .env schedules.json *.pyc
```
`robocopy` reports success with exit codes 0 to 7. Before you hand the copy over, check that it has **no `.env`
file**.

## 2. Install on the new PC
1. Install **Python 3.13** from python.org (classic installer: tick *Add python.exe to PATH*). With the *Python
   install manager* (the `py` command) or winget this step can be skipped: the installer installs 3.13 by itself.
   Python 3.15 can't install the packages yet, so the installer never uses it.
2. Put the folder anywhere the tester can write, for example `C:\Users\<name>\blow-ai`.
3. Double-click **`ui.bat`** (or first `setup\install.bat`, to only install). The first time, the installer creates
   `.venv`, installs the pinned packages and the Chromium browser, and copies `.env.example` to `.env`. This takes a
   few minutes and needs internet. Later starts install only what is missing.
4. Open `.env` and set the AI (see [README, Configure](README.md#3-configure)). Each tester uses their own API keys.
   Without a key, choose **No AI** in the UI: everything still works with the built-in rules.
5. Optional: install Ollama for a local AI, and git for GitHub repos.

If the PC has security software (antivirus, web filter), it may block some test websites or the test values the
tester types into forms. The report then shows the block page. Ask the IT team to allow the websites you test.
Never switch the security software off for a test.

## 3. Check that it works
Use the practice website that comes with the tests. It runs on the PC itself and needs no internet:
1. Open a terminal in the project folder and start DemoShop:
   ```powershell
   .venv\Scripts\python.exe tests\demo_app.py 8765
   ```
2. In the web UI, test `http://127.0.0.1:8765` with **No AI** and a few pages. Optional test account:
   user `demo`, password `Demo#1234`.
3. The run should end with a report (`report.html`) that lists DemoShop's planted problems, such as its broken link
   (404) and its JavaScript error.
4. Press Ctrl+C in the DemoShop window to stop it.

A developer can also run the tester's own tests (see [tests/README.md](tests/README.md)).

## 4. Update to a new version
**With git:** wait for any running test to finish, close the UI window, run `git pull` in the project folder and
double-click `ui.bat`. The tester's data stays where it is (git ignores it). The installer installs the packages
again only if `requirements.txt` / `constraints.txt` changed. Look at `.env.example` for new settings and copy any you want into `.env`.

**Without git:**
1. Wait for any running test to finish, then close the UI window.
2. Rename the old folder, for example `blow-ai` to `blow-ai-old`, and put the new clean copy in its place as
   `blow-ai`.
3. Move the tester's data from the old folder into the new one: `.env`, `runs/`, `baseline/`, `logs/`, `accounts/`
   and `workspace/` (whichever exist).
4. Look at the new `.env.example` for new settings, and copy any you want into `.env`.
5. Double-click `ui.bat`. The new folder has no `.venv` yet, so the installer installs the packages again (a few
   minutes).
6. When it works, delete `blow-ai-old`.

## 5. Move a tester to a new PC
- `runs/` and `baseline/` can be copied: old reports stay readable, and the next run compares with the baseline.
- `accounts/` cannot be moved. Its test accounts are encrypted for one Windows user on one PC (Windows DPAPI). On
  the new PC the tester gives the account again, or allows sign-up again.
- Write `.env` again on the new PC. Don't send API keys by email or chat.

## 6. Remove
Close the UI window and delete the project folder. All of the tester's data is inside it (`runs/`, `baseline/`,
`logs/`, `accounts/`, `.env`).

## Security checklist
- [ ] The copy (or the git repository) contains no `.env`, `accounts/`, `runs/` or `logs/`. More in
      [SECURITY.md](SECURITY.md).
- [ ] Every tester has their own `.env` with their own keys, and `LLM_BUDGET_USD` set to a limit you accept.
- [ ] Testers only test websites they own or have written permission to test (the UI asks for every website).
- [ ] Production websites run with `TEST_ENVIRONMENT=test` or `production` (nothing is sent). `staging` sends forms
      and changes data: only for test copies.
- [ ] GitHub repos are only tested if you trust their code: testing them installs and runs that code on the PC.
- [ ] A `GITHUB_TOKEN` (only needed for private repos and "Apply fixes" Pull Requests) has the smallest rights:
      Contents + Pull requests: write, on the repos it needs.

## Not supported yet: a shared server or Docker
This version is built for one tester on one Windows PC:
- The web UI has **no login**. It is safe only because it answers on 127.0.0.1 alone. On a server, anyone who reaches
  it could start runs against any website and read every report.
- The sandbox for the generated tests uses a Windows Job Object for its memory and process limits, and created
  test accounts are encrypted with Windows DPAPI.
- It has only been tested on Windows 11.

Running it as a shared service would need, at least: a login for the UI with HTTPS, one separate workspace per user,
a Linux sandbox (a container per test run), a secret store for the API keys, and the full test suite run on Linux.
