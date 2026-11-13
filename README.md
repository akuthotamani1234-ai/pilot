# Qpilot – AI website tester

Give it a **website URL**, a **GitHub link** or a **project folder**. It tests the website the way a QA tester would
and ends with a plain-English report. A run has these steps:

1. **Setup**: if you gave code, download it, install it and start it on localhost
2. **Discovery**: visit every page, take a screenshot of each one, learn what every control does
3. **Change detection**: compare with the last run (new, changed and removed pages) and each page's look (visual check)
4. **Test design**: decide what to test (built-in rules, plus the AI if you choose one); you may review the test cases first
5. **Script generation**: write Playwright + pytest scripts
6. **Execution**: run the scripts, screenshot failures (with `TEST_RETRIES`, re-run failures to spot flaky tests)
7. **Failure analysis**: real website bug, broken script, flaky test or network problem?
8. **Self-healing**: if a script broke because the frontend changed (for example a button id), fix the script and run it again
9. **Report**: HTML report with a verdict (Ready, Ready with Risks, Not Ready or Insufficient Evidence)
10. **Baseline**: remember this run, so the next run can detect changes (then Slack / Jira, if they are set up)

The verdict always comes from fixed rules (release gates), never from the AI. The AI helps to design tests and to
explain results; with `VISION` on it also looks at the screenshots of a failed test and may mark it a *test mistake*
or *suspect* (a person confirms), never a proven website bug. The AI is optional: with **No AI** everything still
works with the built-in rules.

## Quick start
On Windows 10 / 11 with [Python 3.13](https://www.python.org/downloads/):
```powershell
git clone <repository-url> blow-ai
cd blow-ai
.\ui.bat
```
The first start installs everything (a few minutes), then opens http://127.0.0.1:8000. Paste a website you may test
and press **Start testing**. No git? Download the repository as a ZIP from GitHub, unzip it and double-click `ui.bat`.

## Contents
1. [Requirements](#1-requirements)
2. [Install](#2-install)
3. [Configure](#3-configure)
4. [Run](#4-run)
5. [Output of a run](#5-output-of-a-run)
6. [Change detection and self-healing](#6-change-detection-and-self-healing)
7. [AI cost](#7-ai-cost)
8. [Safety rules](#8-safety-rules)
9. [Deploy to another PC](#9-deploy-to-another-pc)
10. [For developers](#10-for-developers)
11. [Troubleshooting](#11-troubleshooting)
12. [More documents](#12-more-documents)
13. [Repository layout](#13-repository-layout)

## Key features
- Web testing with Playwright (discovery, design, execution, healing, HTML/Excel reports)
- Android / Appium testing (native APK, installed package, or website in Android Chrome)
- Optional LLM providers (Ollama, OpenAI, Gemini, Anthropic) or **No AI / rules**
- Release gates with plain-English verdicts; secrets redacted from logs and reports
- Local-first privacy controls; optional Slack / Jira / GitHub integrations when configured

## Tech stack
Python 3.13 · FastAPI · LangGraph · Playwright · Appium · pytest · ruff · vanilla HTML/CSS/JS studio UI

## 1. Requirements
- **Windows 10 or 11.** Developed and tested on Windows 11. The web UI, the sandbox limits (Windows Job Object) and
  the encrypted account store (Windows DPAPI) are built for Windows.
- **Python 3.13** (tested; 3.14 also works). If it is missing, the installer (`setup\install.bat`) installs 3.13 by
  itself, with python.org's *Python install manager* (the `py` command) or with winget. **Python 3.15 can't install
  the packages yet** (PyYAML, needed by langgraph, has no ready-made Windows package for it), so the installer never
  uses it. With the classic installer, tick *Add python.exe to PATH*.
- **Internet** for public websites, cloud AI providers and the first install. (The web page loads its fonts from the
  internet; without it, the PC's own fonts are used.)
- Memory: tested on a 16 GB laptop. Every test browser uses memory, so on a smaller PC lower `TEST_WORKERS` in `.env`.
- Optional:
  - [Ollama](https://ollama.com) to use a local AI (free, no page data leaves your PC; slow on a PC without a graphics card)
  - an API key for OpenAI, Google Gemini or Anthropic Claude to use a cloud AI
  - git to download GitHub repos (without git the repo is downloaded as a zip)
  - Node.js / Python, if you test a project from its code (whatever that project needs to run)

## 2. Install
Get the code with `git clone <repository-url> blow-ai` (or download the ZIP from GitHub and unzip it), then
double-click **`ui.bat`** in that folder: it installs whatever is missing and then starts the tester. To only
install, open the **`setup`** folder and double-click **`install.bat`**. The first time, the installer:
1. installs Python 3.13 if it is missing, and creates the Python environment `.venv`
2. installs the packages of `requirements.txt` and the Chromium browser, at exactly the tested versions
   (`constraints.txt` pins every package, also the ones the main packages need)
3. copies `.env.example` to `.env`

This takes a few minutes, once. Every later start checks each part in about 2 seconds and installs only what is
missing: the packages again when `requirements.txt` / `constraints.txt` changed or a package is missing, Chromium if
it was deleted. Double-clicked by itself, `install.bat` waits for a key at the end so you can read what happened.

By hand, the same steps are:
```powershell
cd blow-ai
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
copy .env.example .env
```

## 3. Configure
All settings are in **`.env`**. Each line of `.env.example` explains its setting. Usually you only set the AI:

| You want | Set in `.env` |
|---|---|
| No AI (built-in rules only) | `LLM_PROVIDER=none` |
| Local AI with Ollama | `LLM_PROVIDER=ollama` and run `ollama pull llama3.1` once (or set `LLM_MODEL` to a model you pulled) |
| OpenAI | `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...` (default model `gpt-4o-mini`) |
| Google Gemini | `LLM_PROVIDER=gemini` and `GEMINI_API_KEY=...` |
| Anthropic Claude | `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...` |

The web UI also lets you pick the AI for each run. A key pasted there is used for that run only and never saved.

Other settings you may want:
- Qpilot's UI defaults to **Watch**: one visible Chrome window and a 1,000 ms delay per user action. Uncheck Watch
  for **Fast** execution with isolated headless workers. The live timeline retains actions missed between refreshes.
- `FINALIZATION_RESERVE_S` (default 120) reserves time inside `RUN_TIME_LIMIT_MIN` for deterministic findings and reports.
- `DISCOVERY_BUDGET_FRACTION` (default 0.4) caps discovery's share of the overall budget; `CRAWL_TIME_LIMIT_MIN` remains
  an additional cap. Discovery-only runs retain their selected discovery budget.
- After execution, **AI fixes** reads your selected GitHub repository at a pinned commit. Select supported findings,
  prepare changes, review the diff and validation limitations, then create a pull request. Repository repair uses the
  configured AI provider and privacy policy; temporary API keys from a finished QA worker are not retained.
  Syntax checks are automatic for supported file types; project regression commands require your CI or local review.
- Discovery performs input checks without submitting write forms. Planned authorized fixture/staging workflows retain
  their existing write guards. Interrupted write workflows require record reconciliation before replay.
- `LLM_BUDGET_USD` (default 2): the most a run may spend on the AI. After that it uses the built-in rules.
- `TEST_WORKERS` (default 4): how many browsers run tests at the same time.
- `MAX_PAGES`, `MAX_DEPTH`, `HARD_PAGE_CAP`, `CRAWL_TIME_LIMIT_MIN`, `RUN_TIME_LIMIT_MIN`: how much of the website is
  explored and for how long.
- `TEST_ENVIRONMENT`: `test` (default), `staging` or `production`. See [Environments](#environments) below.
- `VISION` (default `auto`): the AI looks at screenshots (on with a cloud AI or an Ollama vision model; `on` / `off`).
- `TEST_RETRIES` (default 0): run failed tests again to spot flaky ones (1 = once).
- `UI_PORT` (default 8000): the web UI's port.

**`.env` holds your keys. Never share it, copy it to another person or put it in a repository.** `.env.example` is
the empty template that is shared. Git ignores `.env` (see `.gitignore`).

## 4. Run

### Web UI (recommended)
Double-click **`ui.bat`** (or `run.bat`). It opens http://127.0.0.1:8000 in your browser. Keep the black window open
while you use it. Double-clicking again restarts the UI with the latest version (an older open UI window closes by
itself; a test that is still running is never interrupted).

**The chat page** (http://127.0.0.1:8000/):
1. Paste a website URL, GitHub repo or project folder in the chat box. The agent opens the website and shows if it works.
2. It asks which **AI (LLM)** to use. **Ollama** is selected by default; pick Gemini / OpenAI / Claude / No AI if you want,
   choose the model, the number of pages, and whether to **watch the tests in a Chrome window** (on by default:
   ONE real Chrome window shows the whole run, exploring and then every test one after another - you see every
   click live; slower than hidden browsers in parallel).
   - **Website has a login?** Give a **test account** (never a real one). It is used for this run only: never saved,
     never in logs, screenshots, scripts or AI requests. No account? Tick *Allow me to create one* only if creating
     an account on that website is OK - otherwise only the public pages are tested. MFA / CAPTCHA are reported, never bypassed.
   - **⚙ Advanced settings** (all optional - empty = the tester decides): environment (test / staging / production),
     click depth, page timeout, record a video, login page URL, login boxes (CSS), text shown only when logged in,
     extra allowed hosts, paths to leave out, and your **workflows / expected results / user roles** in plain words.
   - Tick **"I own this website, or I have written permission to test it"** (required; remembered per website).
   Press **Start testing**. Missing or wrong setup details get a clear message before anything starts.
3. The **to-do list** on the right ticks ✓ each step as it finishes. The chat posts what happened at each step: the
   pages found, the **test cases** (with a **⬇ Download Excel** button), every test case turning Passed / Failed live,
   and the **final report** with the verdict, what to fix and the **AI cost**.
   - Under each problem in *What you should fix*: **Code now → Change to** (the exact line of the page's HTML/JS and
     the corrected line, with a Copy button). Common HTML problems (`novalidate`, missing `required`, `type="text"`
     on an email box, missing `maxlength`) are fixed by built-in rules; for the rest the AI writes the corrected line
     (check it before use). Server-side code can't be seen, so those problems get advice in words only.
   - The report also shows **why** the verdict is what it is (the **release gates**), **three separate coverages**
     (pages visited / found, controls tested / found, test cases run / designed), the login outcome, **bug reports**
     (steps to reproduce, expected, actual, screenshot + Playwright trace) and **⬇ Test cases (JSON)**.
   - **🔁 Run the same tests again** runs the saved scripts unchanged (a regression run) and shows which test cases
     started failing, were fixed or still fail (test cases keep the same ID, e.g. `TC-3F2A91C0`, in every run).
   - **Apply fixes to your code:** give the website's GitHub repo; *Prepare changes* shows exactly which files and
     lines would change (nothing is sent), *Create Pull Request* puts them on a new branch + Pull Request. The main
     branch is never changed. Needs `GITHUB_TOKEN` with Contents + Pull requests: write.
4. If the AI is slow (e.g. a timeout), the chat says so; that step uses the built-in rules and the test continues.
5. **Recent tests** (left) re-opens any earlier test; **＋ New test** starts again; **■ Stop** stops a run and still
   gives a report of what was done so far.

### Command line
```powershell
.venv\Scripts\python.exe main.py https://the-internet.herokuapp.com --max-pages 15   # a website
.venv\Scripts\python.exe main.py localhost:3000                       # a site already running on your PC
.venv\Scripts\python.exe main.py https://github.com/user/repo         # GitHub code: download, install, run, test
.venv\Scripts\python.exe main.py C:\Users\you\Projects\my-site        # a local project folder
.venv\Scripts\python.exe main.py <source> --show-browser              # watch the browser
.venv\Scripts\python.exe main.py <source> --fresh                     # forget the last run, regenerate everything
.venv\Scripts\python.exe main.py <repo> --start-cmd "npm run dev -- --port {port}"   # if auto-detection fails
.venv\Scripts\python.exe main.py --resume <run folder name>           # go on with a run that stopped
.venv\Scripts\python.exe main.py https://site.com/practice-page/ --scope section    # site | section | page
.venv\Scripts\python.exe main.py https://staging.site.com --env staging             # forms ARE sent (see below)
.venv\Scripts\python.exe main.py https://shop.example.com --section /electronics    # one part of a very large site
.venv\Scripts\python.exe main.py https://shop.example.com --incremental             # only new / changed pages in full
.venv\Scripts\python.exe main.py --merge <run1> <run2> ...            # one report over several --section runs
.venv\Scripts\python.exe main.py --approve-visual <run folder name>   # its changed look becomes the approved look
.venv\Scripts\python.exe main.py <url> --my-test "Search for Blue Top - it is listed"   # your own test, kept for the site
.venv\Scripts\python.exe main.py --recheck <run folder name> [test id]   # after a fix: only that bug's test runs again
.venv\Scripts\python.exe main.py <url> --no-open --exit-code          # CI: exit code 1 when Not Ready / Insufficient Evidence
.venv\Scripts\python.exe main.py --help                               # every option
```
`run.bat <url>` does the same as `main.py <url>`, with the setup check first. Then open the report:
`start runs\<folder>\report.html`.

### What a run tests
What is explored is decided from the link (`CRAWL_SCOPE=auto`): a home page link explores the whole website (up to
`HARD_PAGE_CAP`, 500 pages), a folder link (`site.com/shop`) that section, a deeper link only that page; `--scope`
forces one. **With a test account it logs
in first** (it finds the "Sign in" link itself; one-step and two-step logins), then explores **the pages behind the
login before the public ones**, inspects every page (page type and features: search, filters, sort, pages, options,
cart, wishlist, orders …) and tests every feature it found: a test per feature, user journeys (search → product →
option → cart → the cart lists it; orders → details) and site-wide checks. Pay / order / delete / save / log out are
never clicked: they are listed as **Blocked**.

### Environments
- `test` (default) and `production` never send anything: forms are filled and submitted through a write guard that
  stops the request in the browser, so a form is judged by what it would send.
- `staging` sends forms for real, creates records tagged `qa-<run>-…`, finds, edits and deletes them, and lists
  anything left behind in `created.json` and the report. Delete / logout / password / pay stay blocked unless
  `ALLOW_ACTIONS` names them. On a host without staging / test / qa / dev / uat / preview / sandbox in its name, it
  also needs `--confirm-writes` (a second confirmation in the UI).

### A run always ends with a report
If an agent crashes, you press Ctrl+C (once: it stops at the next safe point; twice: at once), you press **■ Stop**
in the web UI, or the run hits `RUN_TIME_LIMIT_MIN` (90 min), the report is written with everything done so far:
verdict *Insufficient Evidence*, the reason first, and every limit that was hit. Such a run does not become the
baseline. `--resume` goes on before the stage that did not finish (`runs/<run>/checkpoint.sqlite`, deleted when the
run finishes). The test account is never saved, so give it again in `.env` for a resume.

## 5. Output of a run
Every run writes a folder `runs/<site>_<time>/`:

| File | What |
|---|---|
| `report.html` | **Open this.** Verdict, what to fix, changes, healed scripts, failures and screenshots |
| `summary.json`, `metrics.json` | the verdict and its reasons; every number of the report, counted once (the UI reads these) |
| `test_cases.xlsx` | Test cases (steps, expected result, automation + execution status, AI cost per case), results, cost summary |
| `screenshots/` | Every page visited |
| `generated_tests/` | The test scripts (run again any time with `pytest`) |
| `failure_screenshots/` | Screenshot at the moment a test failed |
| `traces/` | Playwright trace of every failed test (open with `playwright show-trace <file>`; passwords removed) |
| `changes.json` | What changed since the last run |
| `visual.json` + `visual/` | The visual check: each page's look vs. its approved look, with the approved / changed pictures |
| `integrations.json` | What was sent to Slack / Jira (only when they are set up) |
| `recheck.json` | Every re-check of a bug after a fix: fixed / still failing, and when |
| `comparison.json` | Test-case results compared with the last run (regression) |
| `crawl.json` | Route coverage: visited / not visited (page limit) / skipped with reason / blocked |
| `login.json` | Login outcome and its evidence (never the password) |
| `healing_log.json` + `healing/` | Which scripts were repaired (old versions kept) |
| `results_pytest_output.txt`, `execution.json` | pytest's own output, sandbox limits, time-limit info |
| `results_junit.xml` | the results in JUnit format, for CI tools |
| `registry.json`, `coverage.json` | every page and feature found with its status; every control found, tested or not (and why) |
| `fixes.json` | the "What you should fix" list, with the code changes |
| `videos/` | a video of the test browsers (only when *Record video* / `RECORD_VIDEO` is on) |
| `console.log` | the whole console output of a run started from the web UI |
| `run_args.json`, `checkpoint.sqlite`, `resume.json` | what `--resume` needs (no password / key / test account) |
| `created.json` | staging only: every record the run created and whether it was deleted again |
| `strength.json` | per test: strong / weak / no check (a test with only weak checks is "smoke", never "verified") |
| `review_request.json`, `review_answers.json` | the human review's questions and your answers |
| `roles.json` | several roles: which page each role could open / was refused (never a password) |
| `jscov.json` | how much of the website's own JavaScript the crawl and the tests used, per script |
| `llm_usage.jsonl`, `cost.json` | every AI call with its tokens, and the cost breakdown |
| `setup.log` | Install / start output when you test code |
| `app_map.json`, `test_cases.json`, `results.json`, `failures.json` | Raw data |

Next to `runs/`:
- `baseline/<site>/` holds the last run's pages and scripts, which the next run compares against. Delete it to
  start fresh.
- `logs/audit.jsonl` records who started, stopped or deleted which test (never secrets).
- `accounts/<site>.json` holds a test account the tester created, encrypted (only if you allowed sign-up).

Old runs can be deleted from the web UI (or delete their folders).

## 6. Change detection and self-healing
Test the same site again after its frontend changed (don't tick *Fresh start*). The second report shows:
- **Frontend changes**: which pages are NEW, CHANGED (buttons / inputs / forms) or REMOVED
- **Self-healing**: tests whose selectors broke (e.g. a button id changed) are repaired and re-run
- Real website bugs are **not** "healed"; they stay reported. A repair may change **how** an element is found, never
  **what** is checked.

**Visual check** (`VISUAL_CHECK=true`, on by default): the first run saves the look of every page, at desktop and at
phone width, as the approved look (`baseline/<site>/visual/`). Later runs show per page what changed: elements that
are gone, moved (a block that moved together is one change) or now overlap, and how much of the picture changed (the
changed pixels in red). Carousels, ads and cookie banners are left out. A change is for you to judge, never a bug by
itself, and the old look stays the approved one until you press **Approve the new look** in the app (or run
`main.py --approve-visual <run>`).

**Your own tests in plain English:** write them in the chat's start card (📝, one per line) or with `--my-test`. They
are kept for that website (`baseline/<site>/my_tests.json`, kept by *Fresh start* too) and every test of it includes
them: the AI turns each one into steps from what it found, then it is scripted and run like the rest. A test the
website can't do, or a run without an AI, shows as *Not automated* with the reason.

**Review before the scripts** (the tick "Let me review the test cases", or `REVIEW=on`): untick test cases you don't
want in this run, answer the questions, add tests of your own. The run waits up to 15 minutes, then goes on.

**Re-check after a fix:** the final report lists the bugs and open questions a test found, each with **🔁 Re-check**:
only that test runs again against the website as it is now, and the answer is *Fixed* or *Still failing*.

**Scheduled tests:** **⏰ Repeat this test** in a report runs it every hour / day / week with the same settings, while
ui.bat is open and the PC is on (a time missed while it was closed is skipped). The list is in the sidebar.

**Multi-step forms:** a later step opened directly by a new visitor (step 2 without step 1) must not be offered. If it
is, you are asked whether that is allowed, the same way as the rules between fields.

**2-step login:** with the test account's authenticator key (`TEST_TOTP_SECRET`, or the chat's login box) the tool
types the login code itself. E-mail / SMS codes still need you in the Chrome window.

**Continuous testing and team tools** (all optional, set in `.env`; see `.env.example`):
- `.github/workflows/blow-ai.yml` tests the website in GitHub Actions after a push, a deployment, every day or by hand, and
  fails the job when the verdict is *Not Ready* or *Insufficient Evidence*. The report is attached to the run.
- `SLACK_WEBHOOK_URL`: one Slack message when a run finds application defects at or above `SLACK_MIN_SEVERITY`.
- `JIRA_URL` + `JIRA_EMAIL` + `JIRA_API_TOKEN` + `JIRA_PROJECT`: one Jira issue per application defect (steps,
  expected / actual, screenshot). The same problem is never sent twice. Test-script problems and inconclusive results
  are never sent.
- `WEBHOOK_TOKEN`: a deploy script on this PC starts a run in the open UI with `POST http://127.0.0.1:8000/api/hooks/run`
  (header `X-QA-Token`, body `{"url": "https://..."}`).

## 7. AI cost
Every AI call is logged with its tokens (`runs/<run>/llm_usage.jsonl`); `cost.json` holds the final breakdown.
- **Overall cost** = the sum of all AI calls in the run (Ollama is always $0).
- **Cost per test case (end-to-end)** = its share of the test-design and script-writing calls for its page, plus any
  self-healing of its own test, plus an equal share of whole-run calls (failure analysis, fix advice).
- Prices are estimates from public list prices, per 1M tokens. Set your own with `LLM_PRICE_INPUT_PER_M` /
  `LLM_PRICE_OUTPUT_PER_M`.
- Example: on Nov 2, 2026 a run on a small public shop with OpenAI `gpt-4o-mini` cost $0.0062 (9 AI calls).

## 8. Safety rules
Details: [project-docs/03_RULES.md](project-docs/03_RULES.md).
- Only test sites you own or may test (confirmed before every test). Only the website's own host is opened
  (+ `ALLOWED_HOSTS`); private networks and cloud metadata addresses are blocked; logout / delete / pay links and
  buttons are never used; no account is created unless you allow it.
- AI-written code is checked before it runs (import allow-list) **and** runs in a sandbox: own process, no API keys,
  no programs / network / file writes outside the run, Windows memory + process limits, per-test time limit.
  This is not a container - see the rules document for the limits.
- Passwords and keys are never shown: they are removed from logs, results, traces and AI requests.
- The web UI only answers on this PC (127.0.0.1 / localhost), and every change needs a header that other websites
  can't send, so another website can't start, stop or delete tests.
- Testing GitHub code runs that code on your PC, so only use repos you trust.
- Big public sites (Amazon, etc.) block bots. Use your own, staging or practice sites.

## 9. Deploy to another PC
Each tester runs their own copy: `git clone` it (or unzip it) on their PC and double-click `ui.bat`. To update later:
`git pull`, then `ui.bat` installs any new packages by itself. See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the
details, what never to copy, checking that it works, and why a shared server is not supported yet.

## 10. For developers

### Project structure
```
blow-ai/
├── backend/              the Python engine: agents, AI wrapper, web server        → backend/README.md
├── frontend/             the web page of the UI (plain HTML / CSS / JS, no build)  → frontend/README.md
├── tests/                tests of the tester + practice websites with planted bugs → tests/README.md
├── project-docs/         product, architecture, rules, design                       → project-docs/README.md
├── main.py               command-line entry point: runs the whole pipeline (used by run.bat and the web UI)
├── setup/install.bat     the installer: Python 3.13, .venv, the packages, Chromium, .env - only what is missing
│                         (double-click it, or ui.bat / run.bat call it before every start)
├── ui.bat                double-click: start the web UI
├── run.bat               double-click = ui.bat;  run.bat <url> = test a site in this window
├── requirements.txt      the app's packages (pinned)
├── constraints.txt       every package's tested version, also the ones the app's packages need
├── requirements-dev.txt  + the code checker and test-only packages
├── pyproject.toml        project info + code checker (ruff) settings
├── pytest.ini            plain `pytest` runs only tests/
├── .env.example          settings template (copy to .env)
├── DEPLOYMENT.md         installing on another PC and updating
├── CONTRIBUTING.md       setting up the code, checking a change, coding rules, commits and Pull Requests
├── SECURITY.md           reporting a security problem, what the tool protects
├── .github/workflows/    ci.yml: ruff + the quick tests on every push to main / Pull Request
│                         blow-ai.yml: test YOUR website in GitHub Actions after a push / deployment (optional)
├── .gitignore            keeps secrets, runs and caches out of git
├── .gitattributes        line endings (the .bat files keep CRLF)
├── .editorconfig         indent, line length and line endings for your editor
│
│   created while you use it (local data, ignored by git, never shared):
├── .env                  your settings and keys
├── runs/                 the output of every run
├── baseline/             the last run per site (change detection) + the approved look (visual/) + jira.json
│                         + your own tests (my_tests.json)
├── schedules.json        scheduled tests (⏰ Repeat this test)
├── accounts/             encrypted test accounts the tester created (only if you allowed it)
├── logs/                 audit.jsonl: who started / stopped / deleted which test
└── workspace/            GitHub repos downloaded for testing
```

### Working on the code
**[CONTRIBUTING.md](CONTRIBUTING.md)** has everything for developers: setting up, the code checker and the tests to
run before a change is handed in, the coding rules, commits and Pull Requests, keeping secrets out of git, and the
known limits of the code base. In short:
```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt               # once: + ruff, vulture, httpx
.venv\Scripts\python.exe -m ruff check .                                      # must say "All checks passed!"
.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile -m "not slow"      # quick regression suite, a few minutes
```
GitHub Actions runs the same checks on every push and Pull Request (`.github/workflows/ci.yml`).

## 11. Troubleshooting
| Problem | What to do |
|---|---|
| `Python 3.13 was not found` / `Could not create .venv` | Install Python 3.13 from python.org (classic installer: tick *Add python.exe to PATH*), then double-click `ui.bat` again. Python 3.15 alone is not enough yet |
| The UI opens on another port | Port 8000 was taken by another program; the UI picks the next free one (or set `UI_PORT`) |
| "A test is running in the UI that is already open" | Wait for that test to finish (or stop it), close the old window, start `ui.bat` again |
| The AI step is slow or times out | Ollama without a graphics card is slow: choose a cloud AI or No AI, or raise `LLM_TIMEOUT` |
| "AI budget ... is used up" | The run spent `LLM_BUDGET_USD`; the rest of the run uses the built-in rules |
| Pages show your antivirus's block page | Security software on the PC blocked the site; the tester never works around it. Ask your IT team, or test from where the site is allowed |
| A big public site answers 403 / CAPTCHA | It blocks bots; test your own, staging or practice sites |
| A run paused for hours | The PC went to sleep; keep it plugged in and awake during long runs |
| `PermissionError` when deleting a test | A file of it (e.g. the Excel file) is open in another program; close it |

## 12. More documents
- [STATUS.md](STATUS.md): what is implemented vs verified (single status page)
- [ARCHITECTURE.md](ARCHITECTURE.md): directory rules, file-size limits, assistant guardrails
- [DEPLOYMENT.md](DEPLOYMENT.md): install on another PC, update, what never to copy
- [docs/15_MCP_INTEGRATION.md](docs/15_MCP_INTEGRATION.md): optional MCP assistant bridge
- [docs/31_PERFORMANCE_AND_LIMITS.md](docs/31_PERFORMANCE_AND_LIMITS.md): configured crawl/test caps
- [CONTRIBUTING.md](CONTRIBUTING.md): branching, Conventional Commits, PR checklist
- [SECURITY.md](SECURITY.md): reporting a security problem, and what the tool protects
- [backend/README.md](backend/README.md): the pipeline and every backend module
- [frontend/README.md](frontend/README.md): the web page and the API it uses
- [tests/README.md](tests/README.md): the tests, the practice websites and the accuracy benchmark
- [project-docs/README.md](project-docs/README.md): product, architecture, rules and design

## 13. Repository layout
```
blow-ai/
├── main.py                 # CLI entry for a single run
├── ui.bat / run.bat        # Windows launchers (install + studio)
├── backend/                # FastAPI server, LangGraph agents, Android/web engines
│   ├── agents/             # Pipeline steps (discovery, design, scripts, report, …)
│   ├── llm/                # Optional provider wrapper
│   └── templates/          # Generated pytest/Appium conftest templates
├── frontend/               # Studio UI (HTML/CSS/JS)
├── tests/                  # Offline pytest suite (+ android_demo fixture)
├── demo-apps/              # Sample contracts (APKs gitignored)
├── docs/ / project-docs/   # Operator and design docs
├── deep_validation/        # Compact validation notes (markdown)
├── STATUS.md               # Implementation vs verification
├── ARCHITECTURE.md         # Placement + assistant guardrails
├── CONTRIBUTING.md         # Branching, commits, PR checklist
├── .env.example            # Public env template (copy to .env locally)
├── requirements.txt        # Direct dependencies
├── requirements-mcp.txt    # Optional MCP SDK extras
└── constraints.txt         # Locked transitive pins
```
Local-only (never commit): `.env`, `.venv/`, `runs/`, `logs/`, `accounts/`, `artifacts/`.

## Native Android testing

Appium + UiAutomator2 testing is available alongside the existing Playwright website workflow.
In Standard testing, **Start Android test** starts the installed local Appium server and boots the selected installed
emulator automatically, then waits for both to be ready before uploading the APK or creating a test run. The setup
panel shows the current preparation step and elapsed time. Selecting Android or refreshing device status only checks
the environment. Missing SDK, Java, Appium or UiAutomator2 installations still need setup; a USB phone must be connected
and authorized. An already running Appium server or emulator is reused.
See [Android setup, safety, AI generation and live demos](project-docs/12_ANDROID.md) and the
[controlled Android fixture](tests/android_demo/README.md). Real device tests are opt-in.

See the [implementation and verification report](project-docs/ANDROID_IMPLEMENTATION_REPORT.md) for actual emulator results, remaining limits and startup commands.

Advanced application checks: [approved flows, business/backend checks, hybrid testing and accuracy lab](project-docs/13_ADVANCED_QA.md).

[Page components, hidden controls and nested-menu inventory](project-docs/14_PAGE_COMPONENT_INVENTORY.md) describes the new crawler inventory. Verification remains deferred.


## Local MCP integration

Optional AI-client access to the existing Playwright/Appium services: install with **setup/install-mcp.bat**, start **ui.bat**, then configure your MCP client using **mcp-config.local.json**. Connection alone never starts a test. See [MCP setup and tools](docs/15_MCP_INTEGRATION.md).


## Choose your workflow and privacy

Select **Playwright or Appium**, then **Standard testing or AI assistant through MCP**. Privacy & connections defaults to local AI processing; cloud providers and MCP data access require approval. See [Workflow and privacy](docs/16_WORKFLOWS_AND_PRIVACY.md).


## Clear website setup and crawl verification

After entering a URL, choose **Account ? AI engine ? Exploration ? More checks**. Whole-site exploration is the default; account creation, AI fallback and limited scope are explicit choices. See [verified behavior and remaining coverage limits](docs/17_CLEAR_SETUP_AND_CRAWL_AUDIT.md).
