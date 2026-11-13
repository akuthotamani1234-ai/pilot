# Changelog

All notable changes to Blow AI should be recorded here. Phase 0 added project status/planning documentation only; it did not alter application code or runtime behavior.

## 2026-11-13 — Coverage gate honesty + Pay Grades vs payment

- Route/feature gates no longer claim exhaustive reachability when exploration is partial
  (`not_tried_limit`, pending URLs, crawl/time limits); prose keeps URLs / route patterns /
  controls / interaction checks / features / workflows and PASS–INCONCLUSIVE denominators separate.
- `metrics.consistent` failures lead summary reasons and the HTML report; provisional/untriaged
  findings keep Insufficient Evidence instead of “zero bugs / none found”.
- Admin config navigation named “Pay Grades” / “Pay Grade” (link/menuitem/tab) is not classified
  as `pay`; real Pay now / Proceed to payment / checkout submits stay blocked, with reasons that
  name `ALLOW_ACTIONS` / `TEST_PAYMENT`.

## 2026-11-13 — Findings finalize on interrupt / empty failures

- `ensure_findings_from_results` builds a rule-based finding for every failed/inconclusive result
  (idempotent merge into `failures.json`; LLM enrichment stays optional).
- Incomplete stop / fallback report paths ingest saved `results.json` / `.jsonl` before gates.
- Reporter and quality gates no longer pass automation-reliability or “no bugs” when failures
  remain unlinked; metrics consistency counts consolidated `nodeids`.

## 2026-11-12 — Studio UI refresh + delete harden

- Static JS/CSS served with `Cache-Control: no-store`; home page shows a visible **build** fingerprint.
- `GET /api/ui-build` returns frontend digests so you can confirm `git pull` + `ui.bat` restart worked.
- Recent **Delete** is always labeled; click does not open the run; server retries folder removal (Windows locks).

## 2026-11-12 — Repo-fix: scan summary and “what you have to do next”

- After a web report, **Apply fixes** still appears when code-bearing findings exist.
- Paste a GitHub link → **Prepare changes** (or Enter): validates `github.com/owner/repo`, scans the repo,
  shows files scanned / matched / hand fixes / advice-only, then an ordered **What you have to do next** checklist.
- `repo_fix.prepare` returns `files_scanned`, `fixes_considered`, `fixes_total`, and structured `no_code` items.

## 2026-11-12 — Studio MCP Android parity, Standard budgets, delete/history

- Android MCP panel mirrors Standard essentials: device + Refresh, Appium URL, optional activity, test-build and
  ownership checkboxes, apk/installed/web (APK as path string). Prepare request includes `get_android_environment`
  then `start_android_test` fields; Standard↔MCP values sync where possible.
- Web Standard intensity reset drops Thorough-forced full/site/80; `explore_repeated_controls` no longer follows
  full crawl alone; server applies Thorough budgets only when `thorough=true` is explicit.
- `/api/history` lists incomplete runs (no `summary.json`); DELETE still removes the runs folder; Recent delete
  control stays visible and clears the open chat after a successful delete.
- In-UI MCP help blurb + short note in `docs/15_MCP_INTEGRATION.md`.

## 2026-11-12 — Thorough mode raises real per-run budgets

- `RunRequest.thorough` raises this-run budgets: repeated controls, ≥80 actions/page (cap 100), ≥60 min crawl,
  ≥500 test cases, `PATTERN_SAMPLES=0`, `QA_THOROUGH=1` (also when full crawl + `explore_repeated_controls`).
- Studio defaults intensity to Thorough; coverage gaps show not-tested counts and **Run Thorough again**.
- MCP `crawl_website` / `start_web_test` default `max_pages=0`, depth 12, and post Thorough fields.
- Coverage honesty: optional `meaning: scripted` + notes that scripted ≠ business-verified; Excel status values unchanged.
- Docs: `docs/31_PERFORMANCE_AND_LIMITS.md`, `STATUS.md`. Coverage remains finite — not every component on every site.

## 2026-11-12 — Live MCP AI-assisted Android test

- Exercised real stdio MCP client against Studio: 11 tools, privacy consent, Sauce MDA Android run.
- Run `android_20261112_105018_1e0c72`: 38 passed, verdict Insufficient Evidence (honest gates).
- Mapped MCP `BridgeError` → `ToolError` so assistants see actionable errors.
- Evidence: `deep_validation/live_runs/mcp_ai_assisted_test_20261112.md`.

## 2026-11-12 — Keep main only; trim deep_validation archive

- Keep production docs: `CHANGELOG.md`, `CONTRIBUTING.md`, `STATUS.md`.
- Slim `deep_validation/` to README + evidence index + `live_runs/*.md` (drop historical phase write-ups).
- Delete merged remote feature branches; only `main` remains as the working branch.

## 2026-11-12 — Docs cleanup + MCP/AI hardening

- Replaced root `FINAL_*` / phase checklist sprawl with a single [`STATUS.md`](STATUS.md).
- Removed raw `deep_validation` pytest dumps and live `.log` files from git; kept markdown assessments.
- Fixed `ask_llm` when `LLM_PROVIDER=none`: clear “AI is turned off… rules are used” error.
- Documented optional MCP install (`requirements-mcp.txt`); verified MCP server registers 11 tools after install.
- Trimmed one-off session review docs under `docs/`.

## 2026-11-12 — Production Git governance

- Expanded `.gitignore` (Android/Gradle locals, artifacts, tool caches, `.claude/`).
- Removed tracked Claude agent metadata (`.claude/agents/*`); guardrails live in `ARCHITECTURE.md`, `.cursorrules`, and `.github/copilot-instructions.md`.
- Updated `README.md` (features, stack, repo tree) and `CONTRIBUTING.md` (branching, Conventional Commits, PR checklist).
- Confirmed `.env` remains untracked; secrets stay in local `.env` / `.env.example` placeholders only.
- No mass split of oversized pipeline modules in this pass (documented for follow-up).

## 2026-11-12 — Thorough exploration preset + ecommerce contract example

- Website setup: **Exploration intensity** Standard / Thorough. Thorough sets full crawl (`max_pages` 0), site scope,
  repeated-control exploration, and at least 50 actions per page; helper text names HARD_PAGE_CAP / time budgets.
- Finished chat reports show a short **Coverage reminder** when not-visited, limit-reached, blocked, or not-tested gaps appear.
- Added `project-docs/examples/ecommerce-web-contract.json` (search → product → add to cart; flows unapproved templates).
- Docs: `docs/17_CLEAR_SETUP_AND_CRAWL_AUDIT.md`, `project-docs/13_ADVANCED_QA.md`. Existing APIs/workflows unchanged.

## 2026-11-12 — Phases 14–16 documentation / hygiene

- Added `docs/31_PERFORMANCE_AND_LIMITS.md`: known config caps (`MAX_PAGES`, `HARD_PAGE_CAP`, workers, timeouts, sandbox) and **measure before optimize**. No invented benchmarks.
- Updated `DEPLOYMENT.md`: Windows remains the primary install/CI target; Linux noted for offline/regression exploration only; light install troubleshooting table.
- Updated `PROJECT_IMPLEMENTATION_STATUS.md`, `MASTER_TODO.md`, and `FEATURE_VERIFICATION_MATRIX.md`: Phases 6–13 marked **IMPLEMENTED**, **not VERIFIED** (full suite deferred by owner), covering Phase 6 env/locator, Phase 7 UX, Phase 8 API, Phase 9 repo-fix partial-match, Phase 10 LLM/MCP errors, Phase 11 security, Phases 12–13 reporting honesty.
- Status vocabulary used: **IMPLEMENTED** / **not VERIFIED** (plus existing historical/partial language). No row claimed **VERIFIED** without test evidence.
- No application logic rewrites; no `.venv` recreated; no runtime artifacts deleted.

## 2026-11-12 — Phases 6–13 implementation slices (code; recorded for status hygiene)

Prior commits on this branch (not re-verified as a full suite here):

- Phase 6: Android environment readiness and native/WebView locator boundary messages.
- Phase 7: Frontend empty/error states and basic a11y.
- Phase 8: API 404s for missing stop/review; `exit_code` on ended jobs.
- Phase 9: Repo-fix partial-match reporting for multi-tag findings.
- Phase 10: Offline AI provider and MCP error-message hardening.
- Phase 11: Safety controls for metadata, private artifacts, and uploads.
- Phases 12–13: Reporting honesty remains code policy (counts from run files; Incomplete → Insufficient Evidence); not a fresh accuracy VERIFIED claim.

## 2026-11-12 — Thorough exploration + ecommerce contract

- UI: Standard/Thorough exploration intensity; Thorough forces full crawl budgets, repeated-control exploration, and ≥50 actions/page; coverage reminder when pages/features were not visited/blocked/not tested.
- Added `project-docs/examples/ecommerce-web-contract.json` template and `demo-apps/ecommerce-web-contract.json` (Automation Exercise search/cart) exposed via `/api/contracts/examples`.
- Documented Thorough crawl knobs in `.env.example`.
- Live thorough run on automationexercise.com: 19 pages visited (pattern sampling), 0 not-visited within limits, 204 tests, 171 passed, verdict Not Ready (no login account; protected actions still blocked).

## 2026-11-12 — Phases 6–18 implementation + Linux Phase 17

- Implemented Phases 6–16 (Android env/locator, frontend UX, API contracts, repo-fix partial match, LLM/MCP errors, security, report clarity, performance/deploy docs).
- Phase 17 Linux non-slow regression: first run 6 failed / 810 passed; after fixes **816 passed**, 2 skipped, 65 deselected; ruff clean.
- Phase 18 delivery reports added: `FINAL_IMPLEMENTATION_REPORT.md`, `FINAL_TEST_REPORT.md`, `FINAL_SECURITY_REPORT.md`, `FINAL_COVERAGE_REPORT.md`, `FINAL_BENCHMARK_REPORT.md`, `FINAL_CHANGELOG.md`, `REMAINING_ISSUES.md`.
- Live Android/cloud LLM/GitHub/MCP sessions remain unverified on this host.

## 2026-11-12 — Phase 0 cloud re-baseline (docs only)

- Re-inspected the Git checkout on the Cursor Linux cloud agent (`/workspace`).
- Updated `PROJECT_IMPLEMENTATION_STATUS.md`, `MASTER_TODO.md`, and `FEATURE_VERIFICATION_MATRIX.md` to separate Windows historical Phase 0–5 evidence from this host.
- Added `deep_validation/13_phase0_cloud_rebaseline.md` with environment facts (Python 3.12 present, 3.13 missing, Git present, no ADB/Appium, no `.venv`/`.env`).
- No application source, tests, APIs, integrations, credentials, baselines, run artifacts or APKs were changed.
- Later phases remain gated pending owner approval; recommended next gate is a Linux Phase 1 regression re-baseline.

## 2026-11-10 — Phase 0 baseline documentation

- Added `PROJECT_IMPLEMENTATION_STATUS.md` with the inspected architecture, evidence status, blockers and repo safety state.
- Added `MASTER_TODO.md` with gated phases and the proposed Phase 1 sequence.
- Added `FEATURE_VERIFICATION_MATRIX.md` distinguishing implementation from fresh/historical verification.
- Added this changelog entry.
- No production source, tests, APIs, integrations, credentials, baselines, run artifacts or APKs were changed.
- Validation evidence remains as recorded in `deep_validation/`; current pytest results are blocked/inconclusive due Windows access-denied temp/process errors, and no current ADB device was available.

## 2026-11-10 - Phase 1 validation update

- Added `deep_validation/08_phase1_results.md` with current commands, results, and the incomplete regression status.
- Focused QA contracts passed using a dedicated directory under standard Windows Temp.
- Non-slow regression did not finish; the one surfaced failure passed when run alone and as part of its test file.
- No application code, tests, assertions, configuration, or existing runtime artifacts were changed or deleted.
## 2026-11-10 - Phase 1 completed

- Focused QA contracts: 23 passed with a dedicated standard Windows Temp basetemp.
- Serial non-slow regression: 751 passed, 65 deselected, exit 0; raw output is in `deep_validation/phase1-pytest-nonslow-serial.txt`.
- The parallel-only busy-server failure did not recur in isolated or full serial runs.
- No source, tests, assertions, configuration, or existing runtime data were changed or deleted. Git initialization remains deferred.

## 2026-11-10 - Phase 2 website discovery

- Fixed XML entity decoding for sitemap `<loc>` URLs and added a regression for query strings containing `&amp;`.
- Made the BigStore acceptance test explicitly set `PATTERN_SAMPLES=3`, matching its documented 3-full/10-smoke sample target for 2,000 slug-based product URLs.
- Verification: focused discovery tests 13 passed; BigStore 3 passed; serial non-slow suite 752 passed with 65 slow tests deselected; Ruff passed on changed files.
- The first BigStore attempt with sampling disabled hit its one-hour run limit and is retained as diagnostic evidence; the configured acceptance rerun passed in 3m21.84s.
- No existing feature or data was deleted; Phase 3 remains gated.

## 2026-11-10 - Phase 3 AI test generation

- Added a grounding check for exact quoted expected text in AI-generated website journeys and owner-authored AI tests. If the exact text is absent from observed site evidence and owner input, the case is marked exploratory and retains the original expectation for review.
- Grounded messages and owner-requested text remain unchanged; rules-only case generation is unchanged.
- Verification: AI test-design/grounding/case-optimization regressions 67 passed; final serial non-slow suite 754 passed, 65 deselected; Ruff passed on changed files.
- No live AI provider was contacted. See `deep_validation/10_phase3_results.md`; Phase 4 was gated at this point.


## 2026-11-11 - Phase 4 execution safety (in progress)

- Windows generated-test execution now fails closed if Job Object memory/process limits cannot be established; it attempts to stop the uncontained pytest process tree and reports an explicit error.
- Added regression coverage for Job Object creation and process-assignment failures.
- Made the sandbox trace regression independent of machine retry settings by explicitly requesting the retry the test asserts.
- Targeted checks passed: executor safety 2/2; sandbox/browser recovery 5/5; Android protocol file 3/3 in isolation; Ruff passed.
- Full serial non-slow run: 755 passed, 65 deselected, 1 Android mock test timed out at its 120-second action budget. The case passed alone and in three additional repetitions; its complete file passed in isolation. Phase 4 remains in progress; see `deep_validation/11_phase4_results.md`.


## 2026-11-11 - Phase 4 completed

- Final verification: executor safety 2/2; sandbox/browser recovery 5/5; Ruff passed; serial non-slow suite 756 passed, 65 slow tests deselected, 0 failed in 28:57.
- The prior Android mock timeout recorded 22,642 seconds on the monotonic timer. A full rerun with a temporary keep-awake request passed; timeout/assertions were unchanged. The system-suspend explanation is strongly supported, not directly confirmed by Windows power event logs.
- Phase 4 is complete. Phase 5 remains gated pending owner approval. See `deep_validation/11_phase4_results.md`.


## 2026-11-11 - Phase 5 failure analysis and self-healing

- Audited the existing classifier, self-healing agent, executor retry/healing decision, graph callers, and regression coverage. No production logic change was needed.
- Corrected the controlled end-to-end healing test setup: the saved learned test's text fallback previously bypassed locator failure, so the real seeded behavior defect correctly appeared without a healing attempt. The test now disables that fallback for the specific stale-selector case while retaining the expected-message assertion.
- Verification: focused classification/healing suite 141 passed, 8 slow tests deselected; DemoStore healing E2E 1 passed in 967.53s; Ruff passed. The selector repair was kept after rerun, and the seeded no-message defect remained `assertion_failure`.
- Phase 5 is complete. Phase 6 remains gated pending owner approval. See `deep_validation/12_phase5_results.md`.
