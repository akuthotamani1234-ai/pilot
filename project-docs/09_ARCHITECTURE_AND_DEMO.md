# Agentic AI Test Quality System – Architecture, Status and Demo

| **Date** | Oct 27, 2026 (sections 4, 5 and 7 updated Nov 4, 2026) |
|---|---|
| **Audience** | Reviewers of the "Agentic AI Test Quality System" architecture proposal |
| **Status** | MVP core loop implemented and verified on the local practice websites (`tests/README.md`) |

**Vision:** enter a web application URL (and a test account). An AI-driven quality system then:
1. explores the application, including everything behind the login;
2. designs test cases;
3. generates and runs Playwright + PyTest automation;
4. analyses the results;
5. recommends whether the release is ready.

---

## 1. End-to-end flow (as implemented)

```
URL + test account + scope ─► Orchestrator (LangGraph) ─► Website Discovery ─► Application Map
   ─► Test Design ─► Automation Generation ─► Static Validation ─► Execution (sandbox)
   ─► Failure Analysis ⇄ Self-healing (re-run) ─► Quality & Release Assessment ─► Report + Recommendation
```

| Step | Stage | Implemented in | Output |
|---|---|---|---|
| 1 | Input | `frontend/chat.html/js` + `backend/server.py` | URL, test account (memory only), environment, scope, limits, workflows |
| 2 | Orchestrator | `backend/graph.py`, `main.py` | Stage order, retries, healing loop, budgets, live progress |
| 3 | Website Discovery Agent | `backend/agents/discovery.py`, `backend/auth.py` | Login first, then every reachable page, logged-in pages first |
| 4 | Application Map | `app_map.json`, `crawl.json`, `login.json` | Routes, controls, page type, features, links, auth needs, inaccessible areas |
| 5 | Test Design Agent | `backend/agents/test_design.py`, `backend/features.py` | Structured cases with stable IDs: journeys, feature tests, per-page cases, site checks, Blocked |
| 6 | Automation Generation Agent | `backend/agents/script_generator.py` | Playwright + PyTest files with fixtures, helpers, waits and assertions |
| 7 | Static checks | `validate_script()` in `script_generator.py` | Import allow-list, banned calls / attributes, structure |
| 8 | Execution Agent | `backend/agents/executor.py`, `templates/conftest.py` | Sandboxed run: results, screenshots, traces, JUnit XML, pytest output |
| 9 | Failure Analysis Agent | `backend/agents/failure_analysis.py`, `self_healing.py` | Evidence-based categories (Rules 5.1), bug reports, controlled self-repair |
| 10 | Quality & Release Assessment | `quality_gates()` in `backend/agents/reporter.py` | Deterministic release gates |
| 11 | Report | `report.html`, `summary.json`, `test_cases.xlsx`, chat view | Verdict, coverage, bugs, evidence, comparison with the last run |
| 12 | Human approval / CI | Blocked list, audit log `logs/audit.jsonl`, JUnit XML | Protected actions wait for a human; machine-readable results |

**Architecture choice:** one Python application with modular agents, as the proposal recommends. Agents are
modules, and the orchestrator is LangGraph. The frontend talks to FastAPI, and every run is its own process.

## 2. How testing goes deep after login (the core requirement)

1. **Verify the page:** the start page is opened (status, title, load time).
2. **Log in first:** if the start page has no login form, the tester opens the "Sign in / Log in / My account" link
   itself. It handles one-step and two-step logins (email → Continue → password).

   Success needs **evidence**:
   - the password box is gone, **and**
   - the address moved or a log-out control appeared, **and**
   - the login still holds after reloading.

   A wrong password, a locked account, MFA, a CAPTCHA or an SSO redirect are each reported, never bypassed.
3. **Explore the app:** pages behind the login always go first. Depth restarts at 0 after login.
   - **Inspected on every page:** every button, link, input box, form, menu, tab, filter and table; its page type
     (list, product, cart, orders, account …); and its features (search, filters, sort, pagination, options,
     add to cart, wishlist, order links …).
   - **Many similar pages** (`/product/1…/999`) are all visited by default (`PATTERN_SAMPLES=0`, within the page
     cap); with `PATTERN_SAMPLES` above 0 only a sample of each address pattern is.
   - **Session expiry** is detected, and the tester logs in again.
   - **401 / 403** is recorded as "needs other permissions".
4. **Design tests for everything found:**
   - one large case per page
   - a test per feature (filter, sort, next page, wishlist, long search …)
   - user journeys (log in; search → product → option → add to cart → cart; orders → order details; menu
     navigation)
   - site-wide checks (pages, JavaScript errors, pictures, links, unusual values in every input box)
5. **Protected actions are never clicked.** Pay, order, checkout, delete, send, save and log out become
   **Blocked** test cases ("needs approval").
6. **Live page-by-page view:** the chat shows one row per page as it is opened and inspected. The row then fills
   with that page's test results.

## 3. Safety, security and reliability controls

| Control (proposal §8) | How |
|---|---|
| Browser security | Only the approved host (+ `ALLOWED_HOSTS`). Private networks and cloud metadata are blocked; redirects outside the scope are discarded. |
| Execution isolation | Own process, no API keys. A runtime guard stops programs, network access and file writes outside the run. Windows Job Object limits memory and process count; per-test and per-run time limits. |
| Credential safety | Passwords live in memory only and are redacted in logs, results, traces and AI requests. A created test account (opt-in only) is DPAPI-encrypted. |
| Human approval | Protected actions are never executed; they are listed as Blocked. Starting a test needs an "I am authorised" confirmation; production needs an extra confirmation. |
| Evidence-based reporting | A test that checked nothing is **Inconclusive**, not passed. Failures keep their screenshot, trace and error. |
| Controlled self-repair | Only selectors may change. Repairs that remove a check are rejected. Originals are kept, and the repaired code is re-validated and re-run. |
| Run limits | Pages, depth, crawl minutes, clicks per page, retries, test cases, AI budget (`LLM_BUDGET_USD`), timeouts. |
| Auditability | `logs/audit.jsonl` (who started / stopped / deleted), `llm_usage.jsonl` (every AI call), stable test-case IDs, the generated code saved per run. |

## 4. Release readiness (deterministic, never the AI)

| Gate | Not met → |
|---|---|
| The run finished; start page opens; tests gave results | Insufficient Evidence |
| App behind the login was tested | Insufficient Evidence (or a risk) |
| Tests produced reliable answers | Insufficient Evidence |
| No blocking website bug (severity ≥ `GATE_BLOCK_SEVERITY`) | **Not Ready** |
| All critical user journeys pass | **Not Ready** (website bug) / risk (unproven) |
| Every reachable page visited, every feature tested or says why not, all tests in time, no other findings | Ready with Risks |

The AI's text explanation never changes the category, the severity or the verdict. With `VISION` on, its look at a
failed test's screenshots may mark the failure a *test mistake* or *suspect* (never a proven bug); the gates then
decide as usual (full table: [Rules 4](03_RULES.md)).

## 5. MVP success criteria – status

| MVP item | Status | Proof (automated test) |
|---|---|---|
| Accept URL, credentials, environment, scope | ✅ | `tests/test_server.py` (validation messages) |
| Discover reachable pages, Application Map | ✅ incl. behind login | `tests/test_deep_exploration.py`, `tests/test_login_discovery.py` |
| Reviewable, structured test cases | ✅ (Excel + JSON, stable IDs) | `tests/test_rules.py` |
| Playwright / PyTest automation | ✅ | `tests/test_end_to_end.py` |
| Controlled execution environment | ✅ (Windows-native sandbox) | `tests/test_sandbox.py` |
| Logs, screenshots, traces, machine-readable results | ✅ | `test_sandbox.py`, `test_end_to_end.py` |
| Report: coverage gaps, failure classes, rule-based recommendation | ✅ | `test_rules.py`, `test_end_to_end.py` |
| Run the same tests again and compare | ✅ | `test_end_to_end.py` (regression run) |

Run all of it: `.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile` (no internet or AI needed). On Oct 26
the suite had 74 tests (all passed in 10 minutes); on Nov 4 it has 330, of which 276 are the quick ones
(`-m "not slow"`) - see `tests/README.md` for the times. On Oct 26 the DemoStore end-to-end run alone took ~4 minutes:
- logged in (two-step); 28 pages discovered and inspected, 24 behind the login, 23 tested and verified
- 6 / 6 critical journeys passed
- "Place order" / "Buy now" / log out never requested
- verdict "Ready with Risks", because of one real finding: the register form has no validation.

## 6. Demo script (about 10 minutes)

**Before the demo** (two terminal windows in `blow-ai`):
```powershell
.venv\Scripts\python.exe tests\demo_store.py 8766      # the practice shop (keep this window open)
ui.bat                                                  # the Blow AI web UI -> opens http://127.0.0.1:8000
```

**On stage:**
1. In the chat, paste `http://127.0.0.1:8766` → it **verifies** the site (reachable, title, time).
2. **Choose the AI.** *No AI (rules)* is fastest and fully offline; Ollama or Gemini work too.
3. **Give the test account.** Open **🔑 Website has a login?** and enter `demo@store.test` / `Store#2024`.
   Point out: it is used for this run only, never saved, never sent to the AI.
4. Tick **"I own this website…"** → **▶ Start testing**.
5. **Show the live page list.** It logs in first (two-step) and the "🔒" pages behind the login appear before the
   public ones. Each row shows its type, controls and features.
6. **Show the test cases** (👁 View test cases / ⬇ Excel): journeys, feature tests, per-page cases, **Blocked**
   actions (Buy now …).
7. **Execution:** each page row fills with ✓ / ✗ / ⛔; the to-do list ticks every stage.
8. **Final report:**
   - verdict and **release gates** (why)
   - coverage: discovered → inspected → tested → verified, features, journeys
   - `/admin` = needs other permissions
   - bugs with screenshots and traces
   - **📄 Open full report**
9. **🔁 Run the same tests again** → comparison with the first run (same test IDs).
10. *(Optional)* the simple practice site: `python tests\demo_app.py 8765` with `demo` / `Demo#1234`.

## 7. Honest limits and next steps

- **Sandbox without Docker:** isolation is OS-level plus a runtime guard, not a container. Next: run tests in a
  Docker container with network rules.
- **Approval screen:** protected actions are reported as Blocked; there is no screen yet to approve and run them
  (on staging, `ALLOW_ACTIONS` allows them in advance). Test cases **can** be reviewed before automation now: the
  review step (`backend/review.py`, "Let me review the test cases" / `REVIEW=on`) lets you untick cases, answer
  questions and add tests.
- **Pause / resume:** `main.py --resume <run>` goes on after the last finished stage of a stopped run (not yet for a
  GitHub / folder project).
- **Storage:** files per run (`runs/<run>/`) plus `baseline/`. Next: PostgreSQL + object storage when several users
  share the system.
- **Reporting integrations:** JUnit XML, Slack, Jira and GitHub Actions (`.github/workflows/blow-ai.yml`) exist;
  Allure is next.
- **MFA / CAPTCHA** are never bypassed: use a test account without them, or a test environment.
- **Real third-party sites:** big public sites (e.g. Amazon) block automation and forbid it in their terms. Test only
  applications you own or are authorised to test.
