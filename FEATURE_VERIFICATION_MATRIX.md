# Blow AI — Feature Verification Matrix

**Initial baseline:** Phase 0 inspection, 2026-11-10. “Implemented” means source paths exist. “Verified” requires actual execution evidence. Historical results are labeled; they are not current-checkout passes. See Phase 1–3 updates below for newer regression evidence.

| Feature/workflow | Principal implementation | Test/evidence | Status |
|---|---|---|---|
| Select Web or Android mode | `frontend/chat.html`, `frontend/chat.js`; `backend/server.py` | Historical UI/device runs documented; current ADB/UI E2E not completed. | Implemented; partially verified historically |
| Web URL/repository/local project setup | `main.py`, `backend/agents/setup_agent.py`, `backend/server.py` | Broad setup tests exist; no fresh successful full suite. | Implemented; current verification blocked |
| Web crawl, links, sitemap, menus, sampling and scope | `backend/agents/discovery.py`, `navigation.py`, `page_inventory.py`, `observe.py` | Phase 2 focused discovery: 13 passed; BigStore: 3 passed, including 2,000 product URLs counted with 3 full/10 smoke samples; serial non-slow suite: 752 passed, 65 deselected. See `deep_validation/09_phase2_results.md`. | Implemented; targeted behavior verified; general-site coverage remains bounded |
| Web login, roles and sessions | `backend/auth.py`, `roles.py`, discovery/test-design agents | Login/deep-exploration/role fixtures; historical controlled runs. | Implemented; partial evidence |
| Web forms, multi-step forms, search, filters, pagination, cart journeys | `forms.py`, `form_rules.py`, `items.py`, `features.py`, agents | Local practice sites and corresponding regression modules. | Implemented; current broad test attempt inconclusive |
| Web test generation/execution | `backend/agents/test_design.py`, `script_generator.py`, `executor.py`, templates | Phase 4 focused safety 2/2; sandbox/browser recovery 5/5; Ruff passed; final serial non-slow suite 756 passed, 65 slow tests deselected. Evidence: `deep_validation/11_phase4_results.md`. | Implemented; Phase 4 verified; live arbitrary-site coverage remains bounded |
| Web failure classification and healing | `failure_analysis.py`, `self_healing.py`, executor | Phase 5 focused suite 141 passed (8 slow marked deselected); DemoStore repair E2E 1 passed, including real-defect preservation. See `deep_validation/12_phase5_results.md`. | Implemented; Phase 5 verified |
| Android APK/installed/Chrome target selection | `backend/android.py`, `android_emulator.py`, `android/server routes`, `chat.js` | Historical APK, installed package and Android Chrome runs. | Implemented; historical device verified, fresh device unavailable |
| Native Android discovery/actions | `android_app.py`, `android_interact.py`, `android_pipeline.py`, runtime/templates | `tests/test_android*.py`; historical 175-pass Android focused suite and controlled app runs. | Implemented; historical verification |
| Android WebView context and CSS locators | `qa_runtime.py`, `android.py`, `android_web.py`, `qa_contracts.py` | Historical hybrid-device run and WebView boundary tests. CSS is rejected in native context. | Implemented; historical verification |
| Android permissions/forms/approved flows | `android_permissions.py`, QA contracts/runtime | Controlled demo app evidence in dated reports; no fresh connected device. | Implemented; historical partial verification |
| Outcome reporting and coverage | `reporter.py`, `metrics.py`, `registry.py`, `android_reporting.py`, Excel | Metrics/results tests; historical XML counts; current run had temp/process errors. | Implemented; latest verification incomplete |
| QA business contracts/API/SQLite oracles | `qa_contracts.py`, `qa_runtime.py`, `qa_oracles.py`, `qa_web.py` | 18 focused tests passed; 5 errored at temp fixture setup. Historical local contract pipeline passed. | Implemented; partial current verification |
| Accuracy benchmark | `qa_benchmark.py`, `accuracy.py`, truth fixtures/UI | Benchmark tests and truth data exist; repeated-device benchmark documented as deferred. | Implemented; general accuracy not established |
| MCP | `mcp_server.py`, `mcp_bridge.py`, `mcp_api.py`, privacy APIs | Tests prepared; MCP status says protocol round trips/live runs deferred. | Implemented; not protocol-verified in current evidence |
| GitHub auto-fix/PR | `repo_fix.py`, FastAPI routes, `frontend/chat.js` | No dedicated functional repo-fix test located; no GitHub service contacted. | Implemented; unverified; partial-match reporting risk |
| Slack/Jira/webhook/schedules | `integrations.py`, `server.py`, `config.py` | Source/tests exist; external integrations not contacted. | Implemented; external behavior unverified |
| Installation/CI/deployment | `setup/`, `ui.bat`, `run.bat`, `.github/workflows/ci.yml`, docs | Ruff/pip checks passed; install scripts and CI not run in Phase 0. | Implemented; partial verification |

## Outcome vocabulary

- **Implemented:** source path and caller exist.
- **Historical verification:** an earlier report/log records execution; it may predate current changes.
- **Partial verification:** some test scenarios ran, but full workflow or target environment coverage is missing.
- **Blocked:** execution could not proceed due a recorded environment prerequisite/error.
- **Unverified:** no execution evidence found for the behavior in the current baseline.

Do not summarize this matrix as “all features work.” Scope and test evidence are explicitly limited.

## Phase 2 verification update - 2026-11-10

The escaped sitemap-query regression and configured large-site sampling case passed. The app default remains `PATTERN_SAMPLES=0`; the BigStore acceptance fixture opts into sampling to match its intended 3-full/10-smoke target. This verifies controlled local scenarios, not exhaustive coverage of arbitrary sites. See `deep_validation/09_phase2_results.md` for exact results and limits.

## Phase 3 verification update - 2026-11-10

AI-generated website journeys and owner-authored AI tests now mark an exact quoted expected result exploratory when that text is absent from observed page evidence and owner-specified requirements. This guard does not prove every unquoted business expectation; live provider behavior also remains unverified. See `deep_validation/10_phase3_results.md`.


## Phase 4 interim verification update (superseded by completion update below) - 2026-11-11

Generated pytest now stops when its Windows Job Object memory/process limits cannot be established. Direct sandbox/browser checks pass. The full non-slow run exposed one Android mock case-budget timeout; that case passed in three additional isolated repetitions, and its complete test file passed in isolation. This interim status was superseded by the full keep-awake rerun and Phase 4 completion update below. See `deep_validation/11_phase4_results.md`.


## Phase 4 completion verification - 2026-11-11

Generated-test execution fails closed when Windows Job Object limits cannot be established. Focused sandbox/browser checks and the full serial non-slow suite passed. The first full-suite run's Android mock timeout coincided with a 22,642-second monotonic case duration; a complete rerun with Windows sleep temporarily prevented passed. Phase 4 is complete. The 65 `slow`-marked tests remain outside this non-slow run. See `deep_validation/11_phase4_results.md`.


## Phase 5 completion verification - 2026-11-11

Rule-based failure classification and self-healing passed the focused regression set. The local DemoStore end-to-end test confirmed a stale selector is repaired and rerun while the seeded missing-message behavior remains a reported `assertion_failure`. The test fixture explicitly prevents the learned helper's name fallback for that one stale-selector case; its expected behavior assertion remains intact. See `deep_validation/12_phase5_results.md`.
