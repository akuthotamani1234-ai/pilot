# backend/ – the testing engine

All of the Python code that tests a website. `main.py` (in the project root) runs it from the command line;
`server.py` runs it for the web UI.

## The pipeline
`graph.py` connects the agents with LangGraph. Each agent is a function `state -> changes to the state`. The state is
the `QAState` dictionary in `state.py`.

```
setup ─▶ discovery ─▶ change_detection ─▶ visual_check ─▶ test_design ─▶ review_gate ─▶ script_generator ─▶ execution
  │          │                                                                               │                ▲      │
  │          │                                                                               │                │      ▼
  │          │                                                                               │       self_healing ◀─ failure_analysis
  │          │                                                                               │       (broken scripts only,     │
  │          │                                                                               │        MAX_HEAL_ROUNDS)         │
  └──────────┴────────── (setup failed / site down / no scripts) ────────────────────────────┴──────────────────────────────▶ report
                                                                                                                               │
                                                                                         save_baseline ─▶ integrations ─▶ END
```

| Step | File | What it does |
|---|---|---|
| setup | `agents/setup_agent.py` | GitHub link or folder → download, install, start it on localhost (skipped for a URL) |
| discovery | `agents/discovery.py` | crawl the website: pages, screenshots, console / network errors, login, item lists, phone width |
| change_detection | `agents/change_detection.py` | compare with `baseline/<site>/` (new / changed / removed pages); also `save_baseline` |
| visual_check | `visual.py` | each page's look (desktop + phone) vs. its approved look: missing / moved / overlapping elements, the changed picture (`VISUAL_CHECK`) |
| test_design | `agents/test_design.py` | the test cases: built-in rules, plus the AI's cases (validated) |
| review_gate | `review.py` | asks a person what the tester can't know (on staging, or `REVIEW=on`) |
| script_generator | `agents/script_generator.py` | the test cases → Playwright + pytest files in `runs/<run>/generated_tests/` |
| execution | `agents/executor.py` | runs pytest in a sandbox, re-runs failures, collects results and traces |
| failure_analysis | `agents/failure_analysis.py` | each failure → website bug / broken script / flaky / network / third party … |
| self_healing | `agents/self_healing.py` | repairs broken selectors (never a check), then runs those tests again |
| report | `agents/reporter.py` | release gates → verdict, `report.html`, `summary.json`, Excel |
| integrations | `integrations.py` | only when set in `.env`: a Slack message, Jira issues for application defects (never sent twice) |

`main.py` saves the state after every agent in `runs/<run>/checkpoint.sqlite`, so `--resume` can continue a stopped
run. A crash, a stop or `RUN_TIME_LIMIT_MIN` still ends with a report (`runctl.py`).

## The other modules

**Settings and run control**
| File | What it does |
|---|---|
| `config.py` | every setting, read from environment variables / `.env` (`settings`) |
| `state.py` | `QAState`: the data passed from agent to agent |
| `runctl.py` | stopping a run on purpose (Ctrl+C, the UI's STOP file, the run time limit) so it still reports |
| `server.py` | the web UI's server (FastAPI): starts `main.py`, streams its progress, serves reports; `POST /api/hooks/run` (with `WEBHOOK_TOKEN`) lets a deploy script start a run; scheduled tests (`schedules.json`, checked every 30 s while it runs) |

**The AI**
| File | What it does |
|---|---|
| `llm/__init__.py` | one wrapper for OpenAI / Gemini / Anthropic / Ollama: `ask_llm`, `ask_structured` (validated JSON), budget, retries |
| `llm/prompts/*.txt` | the instructions sent to the AI (`untrusted.txt` is added to every call: page text may try to give orders) |
| `vision.py` | the AI looks at screenshots (`VISION`): what each page shows, and the before / after pictures of each failed test (website bug, test mistake or can't tell); pages with a password box are never sent |
| `cost.py` | tokens, time and $ of every AI call, per run and per test case |

**Safety**
| File | What it does |
|---|---|
| `safety.py` | which addresses may be opened, secret removal (`redact`), a clean environment for child processes |
| `actions.py` | which clicks are allowed (delete / pay / logout … are blocked unless allowed on staging) |
| `secret_store.py` | a test account the tester created, encrypted with Windows DPAPI (`accounts/<site>.json`) |
| `templates/conftest.py` | copied next to every generated test: fixtures, the sandbox guards, the write guard |
| `templates/pytest.ini` | the generated tests' pytest settings |

**Exploring and understanding pages**
| File | What it does |
|---|---|
| `auth.py` | find the login form, sign in with the test account, prove that it worked; a 2-step login's code from the authenticator key (`totp`) |
| `observe.py` | learn what each control does: observe → act → verify (message, panel, new page, nothing) |
| `features.py` | the page type (listing, product, cart, login …) and the features it really has |
| `items.py` | item lists (products, flights, articles …): open items, compare card and page, next page |
| `mobile.py` | controls only a phone-width page shows, and layout problems at 390 × 844 |
| `roles.py` | several user roles: what each may open; a lower role must stay locked out |
| `jscov.py` | how much of the website's own JavaScript the run used (Chromium) |

**Designing tests**
| File | What it does |
|---|---|
| `forms.py` | forms that create, change or send data: valid / invalid data, create → find → edit → delete on staging |
| `form_rules.py` | rules between fields (date ranges, totals, passengers …), and a multi-step form's later step opened alone |
| `my_tests.py` | your own tests in plain English, kept per website (the AI designs them in `test_design.my_test_cases`) |
| `testdata.py` | test values that fit each input box (read from its label and type) |
| `assert_strength.py` | how strong each generated test's checks are (read from the code), so a weak test is "smoke" |

**Results and the report**
| File | What it does |
|---|---|
| `registry.py` | every page and feature found, with a stable id, the evidence and its test result |
| `metrics.py` | one set of numbers for the whole run (report, chat and Excel use the same) |
| `story.py` | the plain-English text of the report (the verdict sentence, what works, why it matters) |
| `advice.py` | findings → "what you should fix", in priority order |
| `codefix.py` | "Code now → Change to": the exact line of the page's code and the corrected line |
| `repo_fix.py` | apply those fixes to the website's GitHub repo as a Pull Request (never to its main branch) |
| `excel.py` | `test_cases.xlsx`: test cases, results, cost |
| `recheck.py` | re-check after a fix: only the chosen findings' tests run again (`main.py --recheck`, the chat's 🔁 Re-check) |
| `merge.py` | one report over several `--section` runs of a very large website |
| `accuracy.py` | how accurate a run was, measured against a truth file (`python -m backend.accuracy runs/<run>`) |

## Native Android path

`graph.build_graph(target_type="mobile")` selects bounded Appium discovery and the mobile execution adapter.
Shared test-design, script-generation, analysis and report entry points dispatch mobile state to `android_design.py`
and `android_reporting.py`. The existing deterministic verdict engine evaluates mobile evidence gates.
`android_runtime.py` supplies the only actions available to validated generated Python, plus locator-only recovery.
`android.py` handles prerequisites, private APK validation, foreground package boundaries and OS device locks.
`android_runner.py` uses private SQLite checkpoints and supports `--resume`. `mobile.py` remains responsive-web testing.
Test mode ("test everything except checkout", the person's tickbox): `android_interact.py` is the shared core
(fresh state, replay before a test is kept, the coverage list, the never-press rules from
`qa_contracts.never_in_test_mode`); `android_app.py` does the same for a native test build (the app menu first, every screen, the cart, sort, login /
log out) and `android_site.py` explores a website in Android Chrome (every menu first, every
page to its end, then every feature; a pop-up dialog an entry opens - a login or sign-up modal - is a state whose
forms are filled like a page's) and `android_web.py` handles the page reader (what is a menu toggle, a dialog
opener, a form group), bot checks, browser alerts and a fresh visit.
See [Android architecture, setup and verification](../project-docs/12_ANDROID.md).

## How the web UI follows a run
`server.py` starts `main.py` as its own process with `QA_EVENTS=1`. The run then prints marker lines that the server
reads from its output: `::stage::<agent>::start|done`, `::page::{...}` (one inspected page) and `::human::{...}` (a
one-time code or CAPTCHA needs a person). **■ Stop** writes `runs/<run>/STOP`; the run stops at its next safe point and
writes its report. The native runner uses the same stage/page markers and run-status endpoints. Keep these lines
working when you change the console output.

## How the generated tests run
`script_generator.py` writes the tests and copies `templates/conftest.py` + `templates/pytest.ini` next to them.
`executor.py` runs them with pytest (several browsers with pytest-xdist) in their own process:
- without API keys or tokens in its environment (only the test account stays, which the tests read at run time -
  it is never written into the test files),
- inside a Windows Job Object with memory and process limits,
- with guards (in `conftest.py`) against starting programs, opening other hosts and writing files outside the run,
- with a time limit per test and for the whole run.

AI-written test code is also checked before it runs (an import allow-list in `script_generator.py`).

## Rules for changing this code
- **Rules decide, the AI only explains.** The verdict, the failure categories and the severities come from code.
  (One written exception: with `VISION` on, `failure_analysis.classify` lets the AI's look at a failed test's
  screenshots clear it as a *test mistake* or raise it to *suspect* - never to a proven website bug.)
- Every AI call goes through `llm.ask_llm` / `llm.ask_structured`, with a pydantic model for the answer. If the AI
  fails, the agent uses its built-in rules and the run goes on.
- Never print or save a secret: use `safety.redact` for anything that may contain one.
- Never invent a number: count it from the run's files (`metrics.py`).
- Each fixed mistake gets a test in `tests/` that would have caught it.
- Check with `python -m ruff check .` and run the tests (see `tests/README.md`) before you hand a change over.
  Setup, commits and Pull Requests: [../CONTRIBUTING.md](../CONTRIBUTING.md).
