# Qpilot X — final branch acceptance gates

This branch starts at commit `7414a405417a2d411f0eb17ea53d029817e063dc` from `cursor/qx-ready-for-main-cb5b`.

**Status: IN PROGRESS.** Branch name `final` is not a certification of completeness. Existing CI establishes automated regression health, not end-to-end product or production readiness. Phase branch offline suite (2026-11-18): **1204 passed**, 11 skipped (`docs/QPILOT_X_PHASE7_RELEASE_STATUS.md`).

## Acceptance rules

Each capability is **DONE** only when:
1. Its runtime implementation is integrated with the actual web or Android pipeline, not just a standalone helper.
2. Automated unit, integration, and negative tests exercise it.
3. A controlled live target demonstrates expected behavior and produces replayable evidence.
4. Scope limits, blocked/unknown states, costs, and failures are reported without overstating coverage.
5. Security and permissions are validated, with explicit authorization for tested targets.

## Gates to close

| Gate | Required deliverable | Current status |
|---|---|---|
| A | Complete authorized web discovery across page templates, states, DOM, iframe/shadow DOM, API, metadata, lazy content, desktop/mobile | Partial — provenance graph + `surface_coverage.json` (iframe/shadow/API counts); full-surface live completeness not established |
| B | Durable multi-agent supervisor, task ownership, leases, retries, cancellation, checkpoints, budgets, provenance | Partial; SQLite durable queue + supervisor added (`swarm_queue`/`swarm_supervisor`). Redis/Postgres + full agent wiring still open. See `docs/QPILOT_X_PHASE3_SWARM.md` |
| C | Test oracles tied to approved specifications, strong assertions, fixture lifecycle and cleanup | Partial — durable `qx_lifecycle_state.json` + `created.jsonl` confirm; design-time oracle bind softens AI defects; live portal adapters still open |
| D | Browser/API/Android cross-surface execution and evidence-backed coverage | Partial — declarative device matrix (`device_matrix.py`); live emulator evidence still open. See `docs/QPILOT_X_PHASE5_ANDROID_PORTFOLIOS.md` |
| E | Deterministic failure reproduction, locator-only healing, regression safeguards | Partial — bounded `run_saved` on analysis + `healing_policy.json` / locator-only guards; full live failure matrix still open |
| F | Accessibility, visual, performance, safe security, localization and compatibility gates | Partial — a11y/perf/security + first-run `visual.json` capture on apply_run; broad live CI artifacts still open |
| G | Multi-tenant auth/RBAC, PostgreSQL, durable queue, object storage, migrations, isolation and audit | Partial — SQLite `audit_events` persistence + migrations/RBAC/object store; live Postgres/Redis/MinIO isolation still not established |
| H | Hardened deployments, observability, backup/restore drills, load testing, CI/CD and incident operations | Partial foundations — `docs/OPS_DRILL_CHECKLIST.md` + `ops_readiness` (checklist present; observability/DR/load drills still open); gate not complete |
| I | React/TypeScript enterprise dashboard, API versioning, approvals, integration contracts | Partial — `frontend/dashboard` React+TS at `/dashboard/` + `/api/v1`; auth/approvals/hosting still not established |
| J | Repeatable benchmark on a **locally controlled** e-commerce fixture with seeded defects, precision/recall, false positives, flakes, cost and coverage gaps | Strong on DemoStore — run6: 19/19 pages, 24/24 clean features, 6/6 bugs, 0 false alarms (`docs/QPILOT_X_PHASE1_BENCHMARK.md`). Broader sites / Android matrix still open; gate not globally COMPLETE |

## Required live test protocol

- Start with a locally controlled e-commerce test fixture, not an arbitrary production store.
- Seed a documented set of known defects and expected workflows.
- Execute URL-to-report with bounded budgets; store screenshots, traces, network evidence, generated tests and run manifests.
- Record every missed route/state and each blocked/unknown case.
- Run a second time to measure repeatability, flaky outcomes and recovery.
- Only test third-party sites when explicitly authorized; use read-only checks and respect rate limits.
- Native Android validation requires an emulator/device and an authorized APK or package.

## Baseline verification

The source branch passed Ruff and 1,173 non-slow automated tests, with 8 skipped, on GitHub Actions run 44254433522. This does **not** establish all features work against a real site or Android device.

Phase 0 re-baseline on 2026-11-18 (Linux, Python 3.12 venv, Playwright Chromium installed): see
`docs/QPILOT_X_PHASE0_BASELINE.md`. Offline suite after replay-test alignment: target is ruff clean and
non-slow pytest green on the Phase 0 branch. Gate statuses above remain Partial / Not established until
controlled live evidence is linked.

## Completion rule

Do not change this document to `COMPLETE` until all gates A–J have links to commits, automated test runs, controlled live-test artifacts, and an independent review. No system can guarantee discovery of every hidden or inaccessible state; publish measured coverage and explicit unknowns instead.
