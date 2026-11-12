# Blow AI — Master TODO and Phase Gates

**Rule:** Work one phase at a time. Do not start a phase until the owner approves it. Preserve existing behavior; add isolated fixes/tests, run relevant regressions, and report exact evidence before advancing.

## Phase status

| Phase | Status | Gate |
|---|---|---|
| 0 — Project inspection and baseline | **COMPLETE (Windows 2026-11-10; cloud re-inspected 2026-11-12)** | Findings and matrix recorded. Cloud docs-only re-baseline: `deep_validation/13_phase0_cloud_rebaseline.md`. No app source/test edits in Phase 0. |
| 1 - Existing test problems and Git baseline | **COMPLETE on Windows (historical); Linux cloud re-baseline NOT STARTED** | Windows: QA contracts 23 passed; serial non-slow 751→ later 756. Git now exists on this checkout (`925ae2f`). Fresh Linux suite still required before trusting this host. |
| 2 — Website discovery | **COMPLETE (Windows historical)** | See `deep_validation/09_phase2_results.md`. Not re-run on Linux cloud. |
| 3 — AI test generation | **COMPLETE (Windows historical)** | See `deep_validation/10_phase3_results.md`. Not re-run on Linux cloud. |
| 4 - Playwright/Pytest execution | **COMPLETE (Windows historical)** | Job Object fail-closed; see Phase 4 results. Linux Job Object paths are Windows-specific and must not be assumed identical. |
| 5 - Failure analysis and self-healing | **COMPLETE (Windows historical)** | See Phase 5 results. Not re-run on Linux cloud. |
| 6 — Android QA | **IMPLEMENTED** (env/locator offline slice); **not VERIFIED** on device | Clearer ADB/Appium/device unreadiness; CSS blocked in native find, kept for WebView. Full live Android suite deferred. |
| 7 — Frontend | **IMPLEMENTED** (UX hardening); **not VERIFIED** live UI E2E | Empty/error states, basic a11y, escaping; `tests/test_frontend_ux.py`. |
| 8 — API/backend reliability | **IMPLEMENTED**; **not VERIFIED** full surface | Missing stop/review → 404; ended workers expose `exit_code`; successful shapes preserved. |
| 9 — Repository auto-fix | **IMPLEMENTED** (partial-match fix); **not VERIFIED** live GitHub | Multi-tag findings report matched/unmatched; partial ≠ full success. Mocks only. |
| 10 — AI providers and MCP | **IMPLEMENTED** (error-path offline slice); **not VERIFIED** live | Clearer LLMError/BridgeError; blank keys refused; no live provider/MCP round trip claimed. |
| 11 — Security | **IMPLEMENTED** (targeted hardening); **not VERIFIED** as full audit | Metadata SSRF, private artifact serving, APK size limits, redaction tests. |
| 12 — Accuracy/benchmarks | **IMPLEMENTED** (honesty rules in code); **not VERIFIED** full accuracy suite | Accuracy helpers measure from run files; no invented percentages. Labeled clean/seeded live matrix deferred. |
| 13 — Coverage/reporting | **IMPLEMENTED** (count-from-files); **not VERIFIED** export equality suite | Metrics/reporter count from run artifacts; incomplete → Insufficient Evidence. Full export cross-check deferred. |
| 14 — Performance/scalability | **IMPLEMENTED** (docs); measure before any optimization | `docs/31_PERFORMANCE_AND_LIMITS.md` lists config caps only — no fake benchmarks. |
| 15 — DevOps/deployment | **IMPLEMENTED** (docs note); Windows remains primary | `DEPLOYMENT.md`: Linux = offline/regression exploration only; do not recreate `.venv` without approval. |
| 16 — Hygiene/documentation | **IMPLEMENTED** (this pass) | Status/TODO/matrix/changelog updated; no artifact deletion. |
| 17 — Final regression/acceptance | **COMPLETE (Linux non-slow)** | Ruff clean; **816 passed**, 2 skipped, 65 deselected. See `deep_validation/14_phase17_results.md`. Live device/cloud/MCP still open. |
| 18 — Final delivery reports | **COMPLETE** | `FINAL_*.md`, `REMAINING_ISSUES.md`, updated matrix. Distinguish Linux offline vs live verification. |

## Owner decision needed after Phases 6–16 docs

Phases 6–13 are **IMPLEMENTED** with focused offline tests; they are **not VERIFIED**. Recommended next approvals:

1. **Full-suite VERIFICATION** (Windows preferred) — serial `-m "not slow"` with exact counts, then mark rows VERIFIED only where evidence exists.
2. **Live Android** when an emulator/device is available (Phase 6 remaining gate).
3. **Live providers / MCP protocol** only with explicit cost/privacy authorization (Phase 10 remaining gate).
4. Any performance change only after measuring against `docs/31_PERFORMANCE_AND_LIMITS.md` caps (Phase 14).

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

Phase 5 is COMPLETE. Classification/healing regressions passed 141 tests (8 slow-marked tests deselected), and the controlled DemoStore self-healing end-to-end test passed. The initial test attempt exposed an invalid premise: the learned-test helper fell back from the stale selector to the unchanged control name, so the script reached the feature and correctly produced an `assertion_failure`; self-healing correctly refused to rewrite behavior. The regression fixture now disables that fallback only for the saved test under examination, so it exercises the locator-repair path without changing its business assertion. The rerun changed `#notify` to `#notify-me`, kept the pre-repair backup, reran the test and related tests, and classified the seeded missing-message behavior as `assertion_failure` (`repaired`, not healed). Ruff passed. No failure classifier or self-healing production logic needed changing. See `deep_validation/12_phase5_results.md`.

## Phases 6–16 update - 2026-11-12

Phases 6–13 are **IMPLEMENTED** (not VERIFIED; full suite deferred by owner): Phase 6 Android env/locator; Phase 7 frontend UX; Phase 8 API error contracts; Phase 9 repo-fix partial-match; Phase 10 LLM/MCP error messages; Phase 11 security hardening; Phases 12–13 reporting honesty (count from run files, no invented numbers). Phases 14–16 documentation/hygiene: performance limits doc, Windows-primary deployment note, and this status pass.
