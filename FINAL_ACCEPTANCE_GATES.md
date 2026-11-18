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
| A | Complete authorized web discovery across page templates, states, DOM, iframe/shadow DOM, API, metadata, lazy content, desktop/mobile | Partial — provenance graph + discovery-time `surface_coverage.json` (iframe/shadow/API/lazy/metadata/viewport); full-surface live completeness not established |
| B | Durable multi-agent supervisor, task ownership, leases, retries, cancellation, checkpoints, budgets, provenance | Partial — SQLite + Redis DurableQueue adapters, listing dual-write, coverage/oracle specialists; product-wide Redis default + review still open |
| C | Test oracles tied to approved specifications, strong assertions, fixture lifecycle and cleanup | Partial — durable lifecycle + `created.jsonl` + AdminPortal `remote_delete` adapter; broader live portal paths still open |
| D | Browser/API/Android cross-surface execution and evidence-backed coverage | Partial — desktop+phone viewport evidence + Android protocol dry-run contract (never verifies matrix); live emulator/API24+ still open |
| E | Deterministic failure reproduction, locator-only healing, regression safeguards | Partial — persist-then-`run_saved` + flaky→trends wiring + healing_policy; full live failure matrix still open |
| F | Accessibility, visual, performance, safe security, localization and compatibility gates | Partial — a11y/perf/security + first-run `visual.json` capture on apply_run; broad live CI artifacts still open |
| G | Multi-tenant auth/RBAC, PostgreSQL, durable queue, object storage, migrations, isolation and audit | Partial — live Postgres/Redis/MinIO drills + adapters when configured; Studio SSO / multi-tenant ACLs + independent review still open |
| H | Hardened deployments, observability, backup/restore drills, load testing, CI/CD and incident operations | Partial — local drills + CI rollback rehearsal + incident stub under `docs/ops-evidence/`; live hosted DR/soak/paging still open |
| I | React/TypeScript enterprise dashboard, API versioning, approvals, integration contracts | Partial — `/dashboard/` + approvals + auth modes (bearer/webhook/principal+RBAC); SSO/hosting still not established |
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
