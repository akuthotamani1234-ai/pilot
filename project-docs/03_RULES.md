<div style="font-family: 'Segoe UI', Inter, system-ui, -apple-system, Roboto, Arial, sans-serif; line-height: 1.6;">

# 🛡️ Rules & Guidelines

### Blow AI – AI Agents That Test Your Website

| **Version** | 1.0 |
|---|---|
| **Date** | Oct 23, 2026 (checked against the code Nov 4, 2026) |
| **Applies to** | Everyone who uses or changes the project |

These rules are built into the code. Every change to the project must keep them.

---

## 1. Safety Rules (Testing)

- **Same domain only** – the crawler never leaves the website you gave it (plus the hosts in `ALLOWED_HOSTS`).
- **What to test is decided from the link** (the chat says which one it picked):
  - **Entire website** – home page link (`site.com`, `site.com/index.html`) → every page, up to the page limit
  - **Limited pages** – one folder level (`site.com/shop`, `site.com/xpath-practice-page/`) → the pages under it, plus
    the pages their own **content** links to (one step out). Links in the site-wide frame (header, menu, footer,
    sidebar – the same on every page) never take the crawl out of the section: they are listed in `crawl.json` as
    "site-wide menu link, outside the section". A login reached from the section's header keeps the section.
  - **The whole app behind a login** – a login / sign-up link (`site.com/login`, `site.com/client/#/auth/register`), or a
    start page that opens the login → every page of that app (other pages of the domain are kept when they belong to
    it: same name in the title, or mostly the same menu links)
  - **Specific page** – deeper or exact address (`site.com/blog/post`, `?id=5`, `page.html`, `#/cart`) → only that page,
    plus a check of every link on it
  - `--scope site|section|page` (command line) or `CRAWL_SCOPE=site` / `section` / `page` in `.env` forces one mode
- **Single-page apps** – `#/route` addresses (e.g. `#/offers`, `#/cart`) are tested as separate pages.
- **Never click dangerous links** – links with these words are skipped:
  - `logout`, `log-out`, `signout`, `sign-out`, `delete`, `remove`, `unsubscribe`, `deactivate`, `cancel-account`
- **Three kinds of clicks** (`backend/actions.py`):
  - **safe** – view, navigate, search, filter, sort, next page, tabs, menus: used while exploring and testing
  - **test account** – add to cart / wishlist, quantity, choose an option: used by tests only (never while exploring)
  - **protected** – pay, buy, order, checkout, delete, remove, send, post, publish, save, submit, update, change
    password, log out, cancel, transfer …: **never clicked**, listed as **Blocked** test cases (needs approval)
  - Only on **staging** (`TEST_ENVIRONMENT=staging`, the owner's test copy): sending / saving forms is allowed, and
    delete / logout / password / pay only when named in `ALLOW_ACTIONS` (pay also needs `TEST_PAYMENT=1`). A host
    without staging / test / qa / dev / uat / preview / sandbox in its name also needs `CONFIRM_WRITES` (the UI's
    second tick). Even then only the tests made for that action do it – never the exploring.
- **Logged in first, app first** – with a test account the login is done first; pages behind the login are explored
  before public ones; depth starts again at 0 after login. Every route is visited (`PATTERN_SAMPLES=0`, the
  default); set it above 0 to visit only a sample of each address pattern (`/product/{id}`).
- **Never submit forms** in test-data checks – values are only typed in and checked.
  On **test** (the default) and **production** a form test is submitted through a write guard that stops the request
  in the browser (nothing is sent); in **production** the empty-form / invalid-email tests are left out as well.
- **No destructive test cases** – the AI is told never to design tests that delete data, pay, log out or send emails.
- **Only test sites you own** or have permission to test – starting a test needs that confirmation (UI tick).
- **Approved scope** – only the website's own host (+ `ALLOWED_HOSTS`). Cloud metadata addresses are always blocked;
  a public website can never send the tester into your PC / private network. A redirect outside the scope is
  recorded and its content is not used. Downloads are refused.
- **No accounts are created** on a website unless you allow it for that run (`AUTO_REGISTER` / the UI tick).
- **MFA and CAPTCHA are never bypassed** – the login outcome says so and the report shows what could not be tested.
- **Nothing is skipped silently** – every link that is not opened (page limit, unsafe word, file, excluded path,
  same address pattern, other site) is listed with its reason in `crawl.json` and the report.
- **Only use GitHub repos you trust** – their code runs on your PC (there is no Docker sandbox; the app gets a clean
  environment without your keys).

## 2. AI-Written Code Rules

### 2.1 Every Script Is Checked Before It Runs
- Must be valid Python.
- Must have at least one `test_` function.
- **Allowed imports only:** `re`, `json`, `math`, `random`, `string`, `datetime`, `time`, `collections`,
  `itertools`, `functools`, `typing`, `decimal`, `pytest`, `from urllib.parse`, `from playwright.sync_api import
  expect, Page, Locator ...`, and the run's own `steps_*` modules. Everything else is refused.
- **Banned calls:** `eval`, `exec`, `open`, `__import__`, `compile`, `getattr`/`setattr`, `globals`, `vars`, ...
- **Banned attributes:** anything starting with `_`, and everything that could leave the sandbox (`route`,
  `unroute`, `new_context`, `browser`, `expose_function`, `save_as`, `tracing`, `importorskip`, `sleep` ...).
- No `request.post/put/patch/delete/fetch`, no `wait_for_timeout` over 5 s, no file paths in `set_input_files`.

### 2.1b The Sandbox While It Runs (backend/agents/executor.py + templates/conftest.py)
A static check is not a security boundary, so the generated tests also run inside limits:
- **Own process** – never inside the web server or the pipeline.
- **Clean environment** – no API keys, no GitHub token (only the test account, which the tests need).
- **Runtime guard** (Python audit hook) while a test runs: no programs, no network connections, no file writes
  outside the run folder, no reading `.env` / `accounts/`.
- **Browser guard** – only the approved website; private-network and metadata addresses blocked.
  `page.request` may only read (GET / HEAD) and every redirect hop is checked.
- **Windows Job Object** – memory and process-count limits; every browser is killed when the run ends or times out.
- **Time limits** – `TEST_TIMEOUT_S` per test, `SUITE_TIMEOUT_S` for the run.
- **Limit:** this is not a container. With Docker installed, running the tests in a container would be stronger.

### 2.1c A Pass Must Prove Something
- A test that passes without one `assert` / `expect` is **Inconclusive**, never Passed.

### 2.2 When the Check Fails
1. The AI writes its journeys 5 at a time and gets **one chance** to fix each batch's code.
2. If it still fails, that batch's journeys are **left out** (said in the run's log and the coverage notes); your
   own plain-English tests among them stay listed as *Not automated*, with the reason.
3. The built-in test cases are written from templates and always run, with or without the AI.

### 2.3 Code Fixes in the Report
- AI-written fixes are marked **"written by the AI – check it before you use it"**.

## 3. Self-Healing Rules

- **Golden rule:** change **how** an element is found – never **what** is checked.
- A repair that removes or changes assertions is **rejected**.
- Only **script problems** are healed – real website bugs stay in the report.
- Maximum **2 rounds** (`MAX_HEAL_ROUNDS`).
- Tests that could not be healed are **not tried again**.
- Old versions of repaired scripts are kept in `runs/<run>/healing/`.

## 4. Verdict Rules

The verdict is calculated from **release gates** (backend/agents/reporter.py, `quality_gates`) – **never by the
AI**. Each gate is pass / fail / risk / missing evidence; thresholds are in `.env` (`GATE_*`).

| Gate | Fails / missing when |
|---|---|
| The run finished | it crashed, was stopped or hit `RUN_TIME_LIMIT_MIN` → **Insufficient Evidence** |
| The start page opens | the app did not start, or neither the start page nor `GATE_MIN_PUBLIC_PAGES` other pages loaded → **Insufficient Evidence** (only the start page failing → a risk) |
| The pages behind the login were tested | a login exists, nobody could log in, and the app is behind it (`GATE_LOGIN_REQUIRED`) → **Insufficient Evidence** (otherwise a risk) |
| Every reachable page was visited | the page limit was hit → risk |
| Tests were executed | no test gave a result → **Insufficient Evidence** |
| Tests produced reliable answers | ≥ `GATE_MAX_AUTOMATION_ERRORS` of the tests (default 0: any unresolved error) were broken scripts / locator / network / time limit / test data / inconclusive / test mistakes → **Insufficient Evidence** (fewer → a risk) |
| All tests finished in time | the test run hit `SUITE_TIMEOUT_S` → risk |
| No blocking website bug | a website bug of `GATE_BLOCK_SEVERITY` or higher, not low-confidence → **Not Ready** |
| All critical user journeys pass | a high-priority journey failed on a website bug → **Not Ready**; not proven (script problem, not run) → risk |
| Every feature found was tested (or says why not) | features not tested or only clicked, pages not reached → risk |
| No other findings | smaller bugs, console errors, flaky or healed tests → risk |

Order: the run did not finish → Insufficient Evidence · start / tests missing → Insufficient Evidence · a blocker →
Not Ready · other missing evidence → Insufficient Evidence · risks → Ready with Risks · else Ready.

## 5. Failure Classification Rules

### 5.1 Categories (decided by rules from the evidence; each finding has a confidence)
- **Website bug** (`product_defect`) – a check about the website failed → also gets a bug report
  (steps to reproduce, expected, actual, evidence, next action).
- **Expectation not met** (`assertion_failure`) – a control did not do what it did while exploring, or an
  AI-written expectation nobody observed: to review, not a proven bug.
- **Locator / interaction** (`locator`) – the test could not find or use the element (not found, not unique,
  covered): not proof of a website bug; self-healing tries to repair it.
- **Script bug** (`test_defect`) – the script is wrong (coding error, sandbox refusal).
- **Test data** (`test_data`) – a precondition is missing (e.g. no test account).
- **Login / permission** (`auth_problem`) – sent back to the login page, 401 / 403.
- **Infrastructure** – network / browser problem. **Timeout** – the time limit was hit.
- **Third party** (`third_party`) – another website's script, tracker or ad failed: listed, never a risk of this site.
- **Flaky** – failed first, passed on retry (the first failure is kept; retries only with `TEST_RETRIES`).
- **Inconclusive** – the test checked nothing, or the evidence doesn't show whose problem it is.
- **Suspect** / **rule question** (`suspect`, `rule_violation`) – a control did nothing, or a common rule between
  fields was broken: a person decides (review, re-check).
- The AI's text explanation never changes the category, the severity or the verdict. The one exception is its look
  at the screenshots (`VISION`, `backend/vision.py`): it may clear a failure as a **test mistake** (`test_mistake`:
  the website did the right thing), or raise a locator / timeout / expectation failure to **suspect** (a person
  confirms). It never makes a proven website bug on its own. The verdict is then still calculated by the gates.
- Other websites refusing robots (HTTP 400/401/403/405/406/429/999) or briefly failing (5xx) are **skipped** with
  the reason, not reported as broken links.

### 5.2 Severity
- **Critical** – a page failed to load.
- **High** – a website bug, a login / permission problem.
- **Medium** – console errors, failed requests, broken external links, network problems, timeouts, layout problems.
- **Low** – broken images, script bugs, locator problems, flaky tests, third-party failures, test mistakes.

## 6. Privacy and Secrets Rules

- **Ollama is the default** – no page data leaves the computer.
- Pasted API keys go **only to that run's process** and are never saved.
- The UI is told **whether** a key exists – never the key itself.
- `.env` holds real keys and is in `.gitignore` – **never commit or share it**.
- The server listens on **`127.0.0.1` only** and only answers to the host names 127.0.0.1 / localhost
  (protects against DNS-rebinding pages).
- **Every change** (start, stop, delete, repo-fix, shutdown) needs the **`X-Agentic-QA: 1`** header.
- Run names are checked so no one can read files **outside `runs/`**; hidden files, `auth.json`, APKs, Android config
  and contract inputs are never served as public static files.
- **Passwords and keys are redacted** (`[REDACTED]`) in the live log, console.log, results, pytest output, traces and
  AI requests (`backend/safety.py: redact`). AI requests also never contain the test account's user name.
- Typing a password in a visible browser shows `••••••` in the caption bar.
- The saved login (session cookies) lives in `runs/<run>/.private/` and is **deleted when the run ends**.
- A created test account's password is stored **encrypted** (Windows DPAPI: only your Windows user can read it).
- Website text sent to the AI is marked as **untrusted data** (prompt-injection guard, `prompts/untrusted.txt`).
- Start / stop / delete / Pull Request are written to **`logs/audit.jsonl`** (never secrets).

## 7. Pull Request Rules

1. **Prepare** first – shows the exact changes; nothing is sent to GitHub.
2. **Create Pull Request** – only when the user presses the button.
3. Always on a **new branch** – the main branch is never changed.
4. Files changed on GitHub since the preview are **skipped**.

## 8. Reliability Rules

- AI busy (HTTP 429 / 5xx) → **up to 3 tries** (10 s, then 20 s apart).
- AI timeout → **retry once**.
- Still failing → that step uses **built-in rules**; the chat shows one warning.
- Ollama not running → the whole run uses **built-in rules**.
- An app started by Setup is **always stopped** at the end, even after a crash.
- Only **one run at a time** in the UI.

## 9. Coding Rules

- **One agent = one file** in `backend/agents/`.
- An agent takes the state and returns **only the parts it changed**.
- Every AI step needs a **rule-based fallback**.
- AI prompts live in `backend/llm/prompts/*.txt`, **not in Python code**.
- New settings go in `config.py` **and** `.env.example`, with a comment.
- Every AI call goes through **`ask_llm()`** so it is counted in the cost.
- User-facing text is **plain English**.
- Check the code and run the tester's quick tests before sharing: `.venv\Scripts\python.exe -m ruff check .` and
  `.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile -m "not slow"` (more in `CONTRIBUTING.md`).

---

**Related documents:** [PRD](01_PRD.md) · [Architecture](02_ARCHITECTURE.md) · [Design](04_DESIGN.md) ·
[Execution Process](05_EXECUTION_PROCESS.md) · [Installation](06_INSTALLATION.md)

</div>
