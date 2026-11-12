# Blow AI — Master TODO and Phase Gates

**Rule:** Work one phase at a time. Do not start a phase until the owner approves it. Preserve existing behavior; add isolated fixes/tests, run relevant regressions, and report exact evidence before advancing.

## Phase status

| Phase | Status | Gate |
|---|---|---|
| 0 — Project inspection and baseline | **COMPLETE** | Findings and implementation matrix recorded. No app source/test edits. Phase 1 subsequently established the serial non-slow test baseline; Git metadata remains absent. |
| 1 - Existing test problems and Git baseline | **COMPLETE (test baseline)** | Focused QA contracts: 23 passed. Serial non-slow suite: 751 passed, 65 deselected. Git init remains deferred; see deep_validation/08_phase1_results.md. |
| 2 — Website discovery | **COMPLETE** | XML-escaped sitemap URLs, sampled page-pattern discovery, and discovery regressions verified; see `deep_validation/09_phase2_results.md`. |
| 3 — AI test generation | **COMPLETE** | Unsupported exact quoted expected messages are downgraded to exploratory; AI generation regressions and full non-slow suite pass. See `deep_validation/10_phase3_results.md`. |
| 4 - Playwright/Pytest execution | **COMPLETE** | Fail-closed Windows Job Object handling; focused tests and final keep-awake serial regression passed. See Phase 4 results. |
| 5 - Failure analysis and self-healing | **COMPLETE** | Classification and end-to-end repair decision verified; the real seeded defect remains a failure. See Phase 5 results. |
| 6 — Android QA | NOT STARTED | Requires declared emulator/device and controlled fixture availability. |
| 7 — Frontend | NOT STARTED | Characterization tests and API/UI compatibility required. |
| 8 — API/backend reliability | NOT STARTED | Preserve all current routes and client contracts. |
| 9 — Repository auto-fix | NOT STARTED | Add isolated tests; GitHub behavior only via mocks/disposable authorized repo. |
| 10 — AI providers and MCP | NOT STARTED | External providers only with explicit cost/privacy authorization; MCP protocol round trips required. |
| 11 — Security | NOT STARTED | Safe static/dependency review first; no destructive tests. |
| 12 — Accuracy/benchmarks | NOT STARTED | Use labeled, reproducible clean/seeded cases; no assumed accuracy figures. |
| 13 — Coverage/reporting | NOT STARTED | Compare report counts/exports with execution records. |
| 14 — Performance/scalability | NOT STARTED | Measure before optimization; retain local architecture unless requirements change. |
| 15 — DevOps/deployment | NOT STARTED | Do not run installers that can recreate `.venv` without separate approval. |
| 16 — Hygiene/documentation | NOT STARTED | No artifact deletion without explicit approval. |
| 17 — Final regression/acceptance | NOT STARTED | Requires completed phase gates and real declared-target verification. |
| 18 — Final delivery reports | NOT STARTED | Produce only after evidence exists; distinguish historical from fresh results. |

## Phase 1 completion record

- [x] Diagnosed the workspace temp ACL issue; using standard Windows Temp allowed pytest and Playwright subprocesses.
- [x] Ran focused `tests/test_qa_contracts.py`: 23 passed.
- [x] Ran the full non-slow suite serially: 751 passed, 65 deselected, exit 0.
- [x] Reviewed `.gitignore` and checked the project root and parent for Git metadata. `deep_validation/` remains present and not ignored; Git initialization, staging, and commits remain deferred.

See `deep_validation/08_phase1_results.md` for commands and raw-log paths.

## General completion checklist for every later phase

- [ ] Inspect affected implementation, callers, contracts and relevant docs.
- [ ] Record existing behavior and compatible APIs before editing.
- [ ] Make one small, additive change at a time.
- [ ] Add regression coverage for an established bug; do not weaken expectations.
- [ ] Run targeted tests; then relevant regression tests.
- [ ] Record command, environment, exact counts and evidence paths.
- [ ] Mark work `IMPLEMENTED` only after code exists; mark `VERIFIED` only after successful execution evidence.
- [ ] Stop phase progression when regressions or environment blockers remain.

## Constraints carried forward

- No unauthorized external website/app testing.
- No live `.env` secrets opened or disclosed.
- No deletion/replacement of features, tests, run history, baselines, reports, APKs or config.
- No paid/cloud AI call without explicit authorization.
- No production checkout/payment/destructive flow without explicit authorized safe fixture and approval.
- Native Android locators and WebView CSS locators remain distinct.

## Phase 1 interim status (superseded by completion update) - 2026-11-10

Phase 1 is IN PROGRESS; the initial phase table above is superseded by the current evidence. The focused QA contract suite passed with a standard Windows Temp basetemp. The complete non-slow suite remains incomplete: one aggregate run stalled at 95%, and a verbose rerun reached 97% with one test failure before stalling. That test and its whole file passed in isolated serial runs. See `deep_validation/08_phase1_results.md`. Do not begin Phase 2 or initialize Git.
## Phase 1 completion update - 2026-11-10

This update supersedes the earlier IN PROGRESS note. Phase 1 test baseline is COMPLETE: `tests/test_qa_contracts.py` passed 23 tests using a standard Windows Temp basetemp, and the serial non-slow suite passed 751 tests with 65 slow tests deselected (exit 0). The xdist-only busy-server failure was not reproduced in serial runs. Git metadata is absent, `.gitignore` does not exclude `deep_validation/`, and that evidence directory is retained in the workspace. Git initialization, staging, and commits remain deferred; Phase 2 had not started as of this Phase 1 update.

## Phase 2 completion update - 2026-11-10

Phase 2 is COMPLETE. `backend/agents/discovery.py` now XML-unescapes sitemap `<loc>` values, with a regression for escaped query parameters. `tests/test_big_store.py` now explicitly enables its intended `PATTERN_SAMPLES=3` scenario; the test's own acceptance target then passed, including all 2,000 products counted, 3 full samples, 10 smoke checks, the time budget, and all 3 seeded defects. Focused discovery tests passed 13/13, the complete serial non-slow suite passed 752 with 65 slow tests deselected, and Ruff passed on changed source/tests. See `deep_validation/09_phase2_results.md`. Phase 3 remains gated pending owner approval.

## Phase 3 completion update - 2026-11-10

Phase 3 is COMPLETE. AI whole-site flows and owner-authored AI tests now downgrade exact quoted expected text to exploratory when the text appears in neither observed site evidence nor owner-provided requirements. Grounded text remains unchanged. The AI-related regression set passed 67 tests; the final serial non-slow suite passed 754 tests with 65 slow tests deselected; Ruff passed on changed source/tests. Live AI providers were not contacted. See `deep_validation/10_phase3_results.md`. At the time of this Phase 3 update, Phase 4 was still gated; see the newer Phase 4 interim update below.


## Phase 4 interim update (superseded by completion update below) - 2026-11-11

Phase 4 has started. Windows generated-test execution now fails closed when Job Object memory/process limits cannot be created or assigned: it attempts to stop the uncontained pytest process tree and raises a clear error instead of continuing without limits. Regression coverage verifies both setup failure paths. The sandbox integration test explicitly enables the retry it asserts for trace capture; its assertion and password-redaction checks remain unchanged. Targeted safety tests passed 2/2, sandbox/browser recovery tests passed 5/5, and Ruff passed on changed files.

The full serial non-slow run completed with 755 passed, 65 deselected, and one failure after 10:42:06: `test_mobile_generated_pipeline_with_real_pytest_and_mock_appium_transport[True-Not Ready]` exceeded its 120-second Android case budget while opening About, so the conservative verdict was `Insufficient Evidence`. The exact case passed alone (18.15s) and in three additional isolated repetitions (16.20s, 16.61s, 16.09s); the Android protocol file also passed in isolation (33.61s). The timeout is not reproduced in isolation, but its full-suite cause remains unproven. This was the interim gate before the keep-awake rerun; see the Phase 4 completion update below for the resolution. See `deep_validation/11_phase4_results.md`.


## Phase 4 completion update - 2026-11-11

Phase 4 is COMPLETE. The executor fails closed if Windows Job Object memory/process limits cannot be established. The sandbox trace test sets its retry count explicitly, preserving its existing trace and redaction assertions. Executor safety tests passed 2/2, sandbox/browser recovery tests passed 5/5, Ruff passed on changed files, and the full serial non-slow suite passed 756 tests with 65 slow tests deselected in 28:57 (exit 0).

The earlier full run had one Android mock timeout and recorded that case as 22,642 seconds. Python 3.13 uses the same clock for `perf_counter` and `monotonic`, and `perf_counter` includes time during sleep. The machine-suspend explanation is strongly supported, though no Windows sleep event log was captured. The full keep-awake rerun passed without changing the Android timeout, verdict, or assertions. Its temporary keep-awake request was cleared when the command exited. See `deep_validation/11_phase4_results.md`. Phase 5 had not started at the time of this Phase 4 update; it is completed in the Phase 5 update below.


## Phase 5 completion update - 2026-11-11

Phase 5 is COMPLETE. Classification/healing regressions passed 141 tests (8 slow-marked tests deselected), and the controlled DemoStore self-healing end-to-end test passed. The initial test attempt exposed an invalid premise: the learned-test helper fell back from the stale selector to the unchanged control name, so the script reached the feature and correctly produced an `assertion_failure`; self-healing correctly refused to rewrite behavior. The regression fixture now disables that fallback only for the saved test under examination, so it exercises the locator-repair path without changing its business assertion. The rerun changed `#notify` to `#notify-me`, kept the pre-repair backup, reran the test and related tests, and classified the seeded missing-message behavior as `assertion_failure` (`repaired`, not healed). Ruff passed. No failure classifier or self-healing production logic needed changing. See `deep_validation/12_phase5_results.md`. Phase 6 remains NOT STARTED pending owner approval.
