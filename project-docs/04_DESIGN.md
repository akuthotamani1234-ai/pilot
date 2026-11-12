<div style="font-family: 'Segoe UI', Inter, system-ui, -apple-system, Roboto, Arial, sans-serif; line-height: 1.6;">

# 🎨 Design Document

### Blow AI – Screens, Visual Style and Data

| **Version** | 1.0 |
|---|---|
| **Date** | Oct 23, 2026 (checked against the code Nov 4, 2026) |
| **Covers** | UI screens · visual style · output files · Excel · cost |

This document describes how the screens look and behave, and how the results of a run are stored.

---

## 1. Screens

There is one page: **the chat view**. (A 3D view and a guided view also existed; they were removed on Nov 2, 2026,
because they had fallen behind the chat view: no human review, no GitHub fix, no wait for a one-time login code.)

### 1.1 Chat View – `http://127.0.0.1:8000/`

```text
┌──────────────┬───────────────────────────────────────────┬──────────────┐
│ Blow AI      │  example.com                 [Testing…] ■ │ To-do   3/9  │
│ ＋ New test   │                                           │ ▓▓▓░░░░░░    │
│              │  QA  ✓ I found 12 pages…                  │ ☑ Open site  │
│ Recent tests │  QA  ⏳ Now generating the test cases…     │ ☑ Find pages │
│  site-a      │  QA  ✓ 84 test cases saved to Excel        │ ◌ Test cases │
│  site-b   🗑  │      👀 Please go through them…           │ ☐ Scripts    │
│              │      [👁 View test cases] [⬇ Excel]        │ ☐ Run tests  │
│              │  QA  ⏳ Writing automation (Python ·…)     │ …            │
│              │                    [↓ New messages]       │ AI cost $0.02│
│              │  [ Paste a website URL…            ➤ ]   │ ⬇ Excel  📄  │
└──────────────┴───────────────────────────────────────────┴──────────────┘
```

**Layout**
- **Left:** ＋ New test, recent tests (open / delete).
- **Middle:** the chat with the agent, and the message box at the bottom.
- **Right:** the to-do list with a progress bar, AI cost so far, Excel / report / website links.

**Conversation flow**
1. Greeting → the user pastes a URL, repo or folder.
2. **Website check** card – ✓ reachable (title, HTTP status, ms) or ! not reachable.
3. **AI picker** card:
   - engine cards (Ollama = default), model, API key (cloud only)
   - pages to test, 🔑 test account, 📝 your own tests (+ "Let me review the test cases"), ⚙ advanced settings
   - "Watch the tests in a Chrome window" (on by default), "Fresh start", the permission tick (required)
   - **▶ Start testing** (the last choice is remembered, never the key)
4. **Step messages**, in order:
   - pages found
   - *Now generating the test cases…*
   - test cases saved to Excel → table preview, review request, **View** + **Download**
   - *Writing the automation (Python · Playwright · PyTest)…*
   - scripts ready
   - live execution list (Pending → Running → Passed / Failed)
   - script repair (only if needed)
   - **Testing completed** banner
5. **Final report** card:
   - verdict + pass rate, what works well, stats, AI cost
   - what to fix step by step: why it matters, how to fix, code now → change to, Copy
   - Download Excel, Open full report
6. **Apply fixes** offer – GitHub repo → preview → Pull Request.

**Behaviour**
- Auto-scrolls only while you are at the bottom; otherwise shows **↓ New messages**.
- Tab title shows `⏳ Testing…`, `✓ Done`, `✗ Stopped` or `✗ Failed`.
- Browser notification when a run ends while you are on another tab.
- The live case list redraws only when something changes (no flicker).
- AI timeouts → one warning message with a count.
- Excel viewer: sheet tabs, search, status filter, download; close with ✕, Esc or a click outside.
- Light / dark theme follows the system; on narrow screens the side panels slide in (☰ / ✓).

## 2. Visual Style

- **Fonts:** Inter (text), JetBrains Mono (code and log).
- **Accent colour:** indigo `#5b5bf0` with a violet gradient.
- **Status colours:**
  - 🟢 green – passed / ready
  - 🔴 red – failed / not ready
  - 🟠 amber – warning / ready with risks
  - ⚪ grey – insufficient evidence
- **Shapes:** rounded cards (16 px radius), soft shadows.
- **Motion:** short fade-in for messages; turned off when the system asks for reduced motion.

## 3. Data Design

All files of one run are in `runs/<site>_<YYYYMMDD_HHMMSS>/`.

### 3.1 Files Written During the Run
- `app_map.json` – pages with URL, title, status, load time, links, buttons, inputs, forms, errors (Discovery)
- `screenshots/` – full-page screenshot of every page (Discovery)
- `changes.json` – new / changed / removed / unchanged pages (Change Detection)
- `test_cases.json` – every test case (Test Design)
- `test_cases.xlsx` – the Excel file, updated with results later (see section 4)
- `generated_tests/` – `test_journeys.py`, `test_checks.py` + `steps_<page>.py`, `test_features.py`,
  `test_learned.py`, `test_flows_ai.py` (with an AI), `test_site.py`, `test_<page>_data.py`, `test_all_links.py`
  and, when there is something for them, `test_forms.py`, `test_items.py`, `test_mobile.py`, `test_roles.py`,
  `test_field_rules.py`, `test_cleanup.py`; plus `conftest.py` + `pytest.ini`. Re-run any time with `pytest`
  (Script Generator)
- `results.jsonl` – one line per finished test, written live (conftest)
- `failure_screenshots/` – screenshot at the moment a test failed (conftest)
- `llm_usage.jsonl` – one line per AI call: agent, page, test, tokens, seconds, $ (AI wrapper)

### 3.2 Files Written at the End
- `results.json`, `results_junit.xml`, `execution.json` – all results, the JUnit copy, sandbox / time-limit info
  (Execution)
- `failures.json` – category, severity and explanation per failure (Failure Analysis)
- `healing_log.json` + `healing/` – what was repaired + old versions (Self-Healing)
- `cost.json` – final cost breakdown (Report)
- `summary.json` – verdict, reasons, counts; the UI reads this (Report)
- `metrics.json`, `registry.json`, `coverage.json`, `fixes.json` – every number of the report, every page and
  feature with its status, every control tested or not, what to fix (Report / Script Generator)
- `report.html` – **the report to open** (Report)
- `console.log` – full console output (Server)
- `setup.log` – install / start output, code input only (Setup)

### 3.3 Test Case Fields
- `id`, `tc_id` (stable across runs, e.g. `TC-3F2A91C0`), `title`, `page`, `url`
- `type` – smoke, positive, negative, boundary, data, functional, end-to-end, workflow or exploratory
- `priority` – high, medium or low; `risk`
- `feature`, `element`, `preconditions`, `requirement`, `scenario`
- `steps`, `expected`, `test_data`, `test_data_ref`, `automation_note`
- filled by the run: `automation_status`, `execution_status`, `actual_result`, `evidence`, `skip_reason`

## 4. Excel Design (`test_cases.xlsx`)

### 4.1 Sheet "Test Cases"
- Test case, test steps, expected result, test data, priority
- **Automation Status** – Automated / Not automated (by AI, template or reused script)
- **Execution Status** – Passed / Failed / Flaky / Inconclusive / Blocked / Skipped / Not automated / Not run
- Execution time, AI tokens, **AI cost per case**

### 4.2 Sheet "Test Results"
- Every executed test with its outcome, time and error.

### 4.3 Sheet "Cost Summary"
- Total cost, average cost per test case (end-to-end), tokens, time, cost per agent.

### 4.4 Sheets "Summary", "Coverage" and "Features"
- **Summary** – the run's numbers, from `metrics.json` (the same as the report and the chat).
- **Coverage** – every control found on the pages: tested, or not tested and why.
- **Features** – every feature found, with its status (verified, failed, blocked, not tested …) and why.

## 5. Cost Design

- **Overall cost** = the sum of all AI calls in the run (Ollama is always $0).
- **Cost per test case (end-to-end)** = the sum of:
  - its share of the test-design and script-writing calls for its page
  - the self-healing of its own test
  - an equal share of whole-run calls (failure analysis, fix advice)
- All shares **add up to the overall cost**.
- The chat headline shows the **average** (total ÷ number of test cases).
- Prices are estimates from public list prices per 1M tokens.
- Your own prices: `LLM_PRICE_INPUT_PER_M` / `LLM_PRICE_OUTPUT_PER_M` in `.env`.

---

**Related documents:** [PRD](01_PRD.md) · [Architecture](02_ARCHITECTURE.md) · [Rules](03_RULES.md) ·
[Execution Process](05_EXECUTION_PROCESS.md) · [Installation](06_INSTALLATION.md)

</div>
