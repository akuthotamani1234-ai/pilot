# Blow AI — Project Implementation Status

**Baseline date:** 2026-11-10  
**Status:** Phases 0-5 are complete. Phase 6 has not started.  
**Evidence:** `PROJECT_AUDIT.md`, `deep_validation/06_test_evidence_index.md`, and phase result reports 08–10 under `deep_validation/`.

## Product and architecture

Blow AI is a local Windows QA product with two primary execution paths:

1. **Website QA:** FastAPI UI/CLI → LangGraph workflow → Playwright discovery → test design → generated Playwright/Pytest → guarded execution → failure analysis/healing → deterministic report.
2. **Android QA:** FastAPI UI → Android preparation/config validation → separate Android runner/LangGraph workflow → Appium/UiAutomator2/Pytest → Android reporting.

The UI is plain HTML/CSS/JavaScript. Optional areas include local/cloud LLM providers, QA contracts and HTTP/read-only SQLite oracles, MCP, GitHub pull-request fixes, Slack/Jira, schedules and visual checks. The project does not have a Blow AI business database or ORM; run data is primarily files and LangGraph SQLite checkpoints.

## Implementation status

| Capability | Implementation status | Verification status |
|---|---|---|
| Web/Android mode selection and UI | Implemented in `frontend/chat.html` / `frontend/chat.js`; separate backend submission routes exist. | Historical Android UI evidence is documented. Current UI E2E was not rerun successfully in Phase 0. |
| Web discovery, AI test design, Playwright/Pytest | Implemented across `backend/agents/`, `backend/graph.py`, `main.py`, and `backend/templates/`. Sitemap XML entities are decoded; bounded same-design sampling is available; unsupported exact quoted AI expectations are marked exploratory. | Phase 2 and Phase 3 focused, BigStore, and serial non-slow evidence is recorded in `deep_validation/09_phase2_results.md` and `deep_validation/10_phase3_results.md`. |
| Web failure classification, self-healing, reporting | Implemented in agents, metrics, templates and report modules. | Phase 5 focused regressions: 141 passed, 8 slow-marked deselected; controlled self-healing end-to-end: 1 passed. See `deep_validation/12_phase5_results.md`. |
| Android Appium/Pytest, native and WebView support | Implemented across `backend/android*.py`, `backend/android_pipeline.py`, runner and templates. CSS locators are for WebView; native locator strategies are separate. | Historical emulator runs exist. No ADB device was available in the current Phase 0 environment check. |
| QA contracts, business rules and oracles | Implemented in `backend/qa_contracts.py`, `qa_runtime.py`, `qa_oracles.py`, `qa_web.py`. | Historical focused tests/runs exist; current focused pytest run had temp-directory setup errors. |
| MCP | Server, bridge and API code exist. | `MCP_IMPLEMENTATION_STATUS.md` says protocol round trips and live execution remain deferred. |
| GitHub repo fixes | `backend/repo_fix.py` has prepare and PR flows; server/frontend callers exist. | Dedicated functional repo-fix behavior test was not found; GitHub was not contacted. Partial tag-fix reporting is a static-review risk in `PROJECT_AUDIT.md`. |
| Slack/Jira/webhook/schedules | Optional source/configuration paths exist. | External integrations were not contacted or verified in Phase 0. |

## Registered HTTP surface inspected

The routes below were found in `backend/server.py`, `backend/privacy_api.py` and `backend/mcp_api.py`; `/static` and `/runs` are static-file mounts, not API routes.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Main UI. |
| GET | `/api/check` | Check submitted source reachability. |
| GET | `/api/providers` | Provider/model readiness. |
| POST | `/api/runs` | Start web/standard run. |
| GET | `/api/android/environment` | Android/Appium readiness. |
| POST | `/api/android/prepare` | Prepare authorized device/emulator. |
| POST | `/api/mobile/runs` | Start Android/Appium run; APK upload supported. |
| GET | `/api/runs/latest` | Latest job. |
| GET | `/api/runs/{job_id}` | Job status/logs/progress. |
| GET | `/api/pages/{run}` | Page inventory and test status. |
| GET, POST | `/api/runs/{job_id}/review` | Human review state and answers. |
| POST | `/api/runs/{job_id}/stop` | Stop job. |
| GET | `/api/history` | Saved run history. |
| GET | `/api/report/{run}` | Report data. |
| GET | `/api/coverage/{run}` | Coverage data. |
| GET | `/api/cases/{run}`; `/api/cases/{run}/download` | Test cases and download. |
| GET | `/api/excel/{run}`; `/api/excel/{run}/download` | Workbook metadata and download. |
| DELETE | `/api/runs/{run}` | Delete run. |
| GET | `/api/runs/{run}/repo-fix` | Repo-fix metadata. |
| POST | `/api/runs/{run}/repo-fix/prepare`; `/api/runs/{run}/repo-fix/create` | Prepare preview and create GitHub PR. |
| POST, GET | `/api/runs/{run}/recheck` | Start recheck and read status. |
| GET, POST | `/api/schedules`; DELETE `/api/schedules/{sid}` | Manage schedules. |
| POST | `/api/visual/{run}/approve` | Approve visual baseline. |
| POST | `/api/hooks/run` | Token-authenticated webhook run trigger. |
| POST | `/api/shutdown` | Local server shutdown. |
| GET | `/qa-lab` | QA lab page. |
| GET | `/api/contracts/schema`; `/api/contracts/examples`; `/api/contracts/examples/{example_id}` | Contract schema/examples. |
| POST | `/api/contracts/validate` | Validate contract. |
| POST | `/api/qa/benchmark` | Create benchmark report. |
| GET | `/api/components/{run}` | Page/component inventory. |
| GET, PUT | `/api/settings/privacy` | Read/update privacy policy. |
| GET | `/api/mcp/connection`; `/api/mcp/config`; `/api/mcp/info`; `/api/mcp/jobs`; `/api/mcp/jobs/{job_id}`; `/api/mcp/reports/{run}` | MCP connection, config, jobs, reports. |
| POST | `/api/mcp/heartbeat` | MCP client presence heartbeat. |

The exact request/response contracts are defined in the endpoint handlers and Pydantic models; a full OpenAPI contract-diff was not part of Phase 0.

## Provider and external integration inventory

- **AI:** Ollama (local), OpenAI, Gemini, Anthropic, and `none`/rules mode (`backend/llm/`, `config.py`, `privacy.py`). No provider was called during Phase 0.
- **Browser/device:** Playwright Chromium; Appium/UiAutomator2, Android SDK/ADB, JDK and ChromeDriver. ADB had no connected device during the current environment check.
- **GitHub:** clone/download setup and REST-based branch/PR creation (`setup_agent.py`, `repo_fix.py`); not contacted.
- **Slack/Jira:** optional notifications/issues (`integrations.py`); not contacted.
- **Webhook:** token/signature-checked local run trigger (`/api/hooks/run`); not invoked.
- **QA oracles:** bounded approved-origin HTTP reads and read-only configured SQLite (`qa_oracles.py`); current fixture suite was blocked in part by temp-directory setup.
- **MCP:** stdio server to loopback UI/API; protocol-level round trip remains documented as deferred.

## Baseline execution evidence

These are results already recorded in the workspace or in the immediately preceding validation; they are not represented as one clean current full-suite run:

- Ruff: passed (`ruff check . --no-cache`).
- `pip check`: passed (`No broken requirements found`).
- Focused `tests/test_qa_contracts.py`: 18 passed, 5 setup errors because Windows denied access to pytest’s temp directory.
- Non-slow suite attempt: 406 passed, 21 failed, 324 errors. The output shows temp-directory and Playwright subprocess `PermissionError [WinError 5]` errors; do not interpret the run as a clean baseline or attribute every failure to product code.
- Historical `logs/appium-final-regression.xml`: 175 passed, 1 skipped, 0 failures/errors (2026-11-08).
- Historical `logs/appium-web-regression.xml`: 1 passed (2026-11-08).
- Historical controlled Android run `runs/advanced_android_20261108_162006_clean`: 13 passed, 0 failed; seeded run `runs/advanced_android_20261108_162418_seeded`: 8 passed, 5 failed as expected by the fixture, with `Not Ready`.
- Current Appium readiness check found Appium, JDK, Android SDK and UiAutomator2, but no connected ADB device. The `blowai-api36` AVD did not register in ADB during the attempted startup; no fresh device test was run.

## Repository and safety state

- Intended root is `C:\Users\manikanta.akuthota\OneDrive - Qentelli\Desktop\Blow Ai` (contains `main.py`, `backend/`, `frontend/`, tests and project docs).
- No `.git` metadata was found at the project root or its parent; `git rev-parse --show-toplevel` fails. Tracked/untracked state and revision history are unknown. Git initialization belongs to a later approved phase.
- `.gitignore` excludes `.env`, run/baseline/workspace/account/log data, local state, caches, snapshots, private data, APKs and the local ChromeDriver binary. It does not currently list `deep_validation/`; its intended long-term tracking policy should be decided before Git initialization.
- `.env` exists and was not opened. Secrets were not inspected or copied.
- Existing outputs, baselines, APKs, configs, tests and application source were not deleted or rewritten.

## Known blockers and limits

1. Fix or work around pytest temp/process access restrictions before treating a fresh regression run as evidence.
2. Restore ADB/AVD readiness before current live Android verification.
3. MCP protocol, latest advanced-QA/UI changes and optional external integrations require their separately scoped verification.
4. “Every functionality” cannot be guaranteed on arbitrary sites/apps; crawl/time/action/test limits, unreachable states, protected actions and application-specific expected behavior must remain explicit in reports.

See `MASTER_TODO.md` for the phased plan and `FEATURE_VERIFICATION_MATRIX.md` for evidence by feature.

## Phase 2 verification update - 2026-11-10

- Sitemap URL parsing now decodes XML entities before following URLs; a regression covers `&amp;` in a query string.
- BigStore verifies the configured pattern-sampling path: 2,000 product URLs counted, 3 fully visited, 10 smoke-checked, under budget, with all 3 seeded bugs detected.
- Focused discovery regressions: 13 passed. Serial non-slow suite: 752 passed, 65 deselected. Ruff: passed on changed files.
- The initial BigStore run without `PATTERN_SAMPLES` set hit the one-hour time limit; the test fixture was corrected to opt into its documented sampling acceptance case. Project default remains unchanged (`PATTERN_SAMPLES=0` means visit every route/item subject to configured caps).
- See `deep_validation/09_phase2_results.md` for command/output evidence and remaining coverage limits.

## Phase 1 verification update - 2026-11-10

- Focused `tests/test_qa_contracts.py`: 23 passed using a dedicated directory under standard Windows Temp.
- Complete serial non-slow suite: 751 passed, 65 deselected, exit 0. Raw log: `deep_validation/phase1-pytest-nonslow-serial.txt`.
- The busy-server discovery test failed only in the interrupted xdist aggregate run; it passed alone, in its full test file, and in the serial full suite. The xdist failure was not reproduced.
- Pytest basetemp under `deep_validation/` still encounters the workspace ACL restriction. Standard Windows Temp provided a working test location.
- Source integrity check: 285 of 287 Phase 0 manifest entries are unchanged; the two differences are the intended `MASTER_TODO.md` and `CHANGELOG.md` documentation updates. No application source or test files changed.
- Phase 1 test baseline is complete. Git metadata remains absent and Git initialization is deferred. `deep_validation/` remains present and is not excluded by `.gitignore`.

## Phase 3 verification update - 2026-11-10

- `backend/agents/test_design.py` checks exact quoted expected text in AI whole-site journeys and owner-authored AI tests against the crawler's site summary plus owner requirements/test text. Unsupported exact text is marked `Exploratory:` and the case type becomes `exploratory`; the original expectation remains attached for human review.
- Grounded text and rules-only generation remain unchanged.
- AI-related test files: 67 passed. Final serial non-slow regression: 754 passed, 65 deselected in 1495.05s (24m55s), exit 0. Ruff passed on changed source/tests.
- No external LLM provider was called; provider behavior and app-specific business-rule accuracy still need authorized verification.
- See `deep_validation/10_phase3_results.md`. At the time of this Phase 3 update, Phase 4 was still gated; see the newer Phase 4 interim update below.


## Phase 4 interim verification update (superseded by completion update below) - 2026-11-11

- `backend/agents/executor.py` now stops generated pytest if Windows Job Object limits cannot be established; `tests/test_executor_safety.py` covers creation and process-assignment failures.
- `tests/test_sandbox.py` explicitly enables the retry needed for its trace/redaction assertion, independent of the machine's `TEST_RETRIES` value.
- Targeted checks: executor safety 2 passed; sandbox/browser recovery 5 passed; Android protocol file 3 passed in isolation; Ruff passed on changed files.
- The first full run reported one Android mock timeout. This interim status was superseded by the keep-awake full rerun documented below; Phase 4 completed with 756 passed and 65 slow tests deselected.
- See `deep_validation/11_phase4_results.md`.


## Phase 4 completion verification - 2026-11-11

- Windows generated pytest now fails closed if Job Object memory/process limits cannot be established; creation and assignment failure paths are covered by two regressions.
- Sandbox/browser recovery integration: 5 passed. Ruff passed on changed implementation/tests.
- Final full serial non-slow regression: 756 passed, 65 deselected, 0 failed in 28:57; log: `deep_validation/phase4-pytest-nonslow-awake-rerun.txt`. The 65 deselected tests carry the `slow` marker.
- The earlier full-run Android mock timeout recorded a 22,642-second case duration. Python 3.13 documentation states `perf_counter` includes sleep and, since Python 3.13, uses the same clock as `monotonic`; a system-suspend delay is strongly indicated. A full rerun with a temporary Windows keep-awake request passed.
- Phase 4 is complete. Phase 5 was awaiting owner approval at this point; it is completed in the Phase 5 update below. Details: `deep_validation/11_phase4_results.md`.


## Phase 5 completion verification - 2026-11-11

- Failure-classification and self-healing focused suite: 141 passed, 8 slow-marked tests deselected.
- Controlled DemoStore repair end-to-end test: 1 passed in 967.53 seconds. It verified selector-match repair from `#notify` to `#notify-me`, preservation of a pre-repair backup, a rerun with related tests, and retention of the seeded no-message failure as `assertion_failure`.
- Ruff on `tests/test_end_to_end.py`: passed.
- The first E2E attempt exposed a test-fixture premise issue, not a product-code bug: runtime text fallback located the renamed button, so there was no locator failure to heal. The fixture now disables that fallback for the specific saved test while preserving its expected-message assertion.
- No failure-analysis/self-healing production logic was changed. Phase 5 is complete; Phase 6 has not started. See `deep_validation/12_phase5_results.md`.
