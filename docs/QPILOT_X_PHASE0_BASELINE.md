# Qpilot X — Phase 0 baseline inventory

**Date:** 2026-11-18  
**Working branch:** `cursor/qpilot-x-phase0-baseline-f72b` (from `origin/final` @ `facc584`)  
**Tracker:** [GitHub issue #22](https://github.com/akuthotamani1234-ai/pilot/issues/22)  
**Source of truth:** Expanded 22-section Master Blueprint + `FINAL_ACCEPTANCE_GATES.md`

This document establishes evidence for Phase 0. Module presence is **not** gate completion.

## 1. Baseline commands and results

| Check | Command | Result |
|---|---|---|
| Lint | `.venv/bin/ruff check .` | All checks passed |
| Offline suite (after Chromium install, pre-fix) | `.venv/bin/python -m pytest -q -n 3 --dist loadfile -m "not slow"` | 1174 passed, 11 skipped, **1 failed** |
| Offline suite (post replay-test alignment) | same | **1175 passed**, 11 skipped, 0 failed |
| Replay / swarm smoke | `tests/test_replay_execution_truth.py`, `tests/test_swarm*.py` | Passed |
| Environment | Linux, Python 3.12.3 venv (project targets 3.13; suite still runnable) | Chromium Playwright v1248 installed |

### Regression found on `final` and fixed here

`tests/test_continue_rules.py::test_a_complete_package_names_the_test_that_can_run_again` still mocked `recheck` with only `verdict` and no `outcome`. After the intentional replay-truth change in `backend/replay_pack.run_saved`, that mock no longer counts as executed. Phase 0 aligns the test with the execution-truth contract.

## 2. Pipeline agents present today

| Agent file | Role today |
|---|---|
| `backend/agents/setup_agent.py` | Run setup |
| `backend/agents/discovery.py` | Web discovery / crawl |
| `backend/agents/test_design.py` | Test design |
| `backend/agents/script_generator.py` | Generated scripts |
| `backend/agents/executor.py` | Execution |
| `backend/agents/failure_analysis.py` | Failure analysis |
| `backend/agents/self_healing.py` | Locator healing |
| `backend/agents/reporter.py` | Reporting |
| `backend/agents/change_detection.py` | Change detection |

Blueprint swarm roles (DOM mapper, API mapper, visual mapper, oracle agent, coverage verifier, safety guardian, etc.) exist partly as **helper modules**, not as durable leased workers with typed envelopes end-to-end.

## 3. Advanced capabilities A01–A18 inventory

| ID | Module evidence | Gate status |
|---|---|---|
| A01 Swarm protocol | `backend/swarm*.py` + Redis durable queue drills + `qx_core_capabilities_drill` | Strong offline/Redis; product-wide review open |
| A02 Explore scoring | `backend/explore_score.py` + `qx_capabilities_drill` | Strong offline; live crawl priority open |
| A03 Coverage verifier | `backend/coverage_verify.py` + `qx_core_capabilities_drill` | Strong offline; live discovery completeness open |
| A04 Oracles | `backend/oracle.py` + `qx_core_capabilities_drill` | Strong offline; live portal oracles open |
| A05 Data lifecycle | `backend/data_lifecycle.py` + lifecycle drills + `qx_core_capabilities_drill` | Strong offline/fixture; broader live cleanup open |
| A06 Identity/sessions | `backend/sessions.py` + `qx_core_capabilities_drill` | Strong offline vault refs; hosted IdP open |
| A07 Env virtualization | `backend/env_controls.py` + `qx_capabilities_drill` | Strong offline; hosted env open |
| A08 Deterministic replay | `backend/replay_pack.py` + `qx_core_capabilities_drill` | Strong offline package completeness; production replay suite open |
| A09 Mutation scoring | `backend/mutation_score.py` + `mutation_score_drill` | Strong (DemoStore 6/6); third-party open |
| A10 Cross-platform journeys | `backend/journey_map.py` + `cross_platform_journey_drill` | Partial (web engines + optional Android) |
| A11 Localization | `backend/locale_check.py` + locale portfolio + `qx_core_capabilities_drill` | Strong offline; hosted multi-locale CI open |
| A12 Agent evaluation | `backend/agent_eval.py` + `qx_capabilities_drill` | Strong offline; live model-gate open |
| A13 Incremental discovery | `backend/incremental_map.py` + `qx_capabilities_drill` | Strong offline; live incremental crawl open |
| A14 Dependency faults | `backend/dependency_fault.py` + `qx_capabilities_drill` | Strong offline; staging inject open |
| A15 Schema evolution | `backend/schema_diff.py` + `qx_capabilities_drill` | Strong offline; live contract open |
| A16 Human review | `backend/human_review.py` + `qx_capabilities_drill` | Strong offline; Studio UX open |
| A17 Quality trends | `backend/quality_trends.py` + `qx_capabilities_drill` | Strong offline; live trend feed open |
| A18 Plugin SDK | `backend/plugins.py` + `qx_capabilities_drill` | Strong offline; plugin marketplace open |

## 4. Acceptance gates A–J (current)

Synced with `FINAL_ACCEPTANCE_GATES.md` + Studio `/api/v1/blueprint/progress` (branch
`cursor/qpilot-x-phase0-baseline-f72b`). Gates stay Partial/open until hosted +
independent evidence closes the six hard blockers.

| Gate | Status |
|---|---|
| A Discovery completeness | Partial — multi-fixture surfaces + discovery score + surface matrix; full live completeness open |
| B Durable swarm | Partial — Redis DurableQueue + contention/control/retry; product-wide review open |
| C Oracles + fixture cleanup | Partial — multi-portal oracles + Demo/Admin/Classic lifecycles; broader portal paths open |
| D Web/API/Android surfaces | Partial — API24 smoke + API30 Appium + ApiDemos deep + journey; broad multi-device CI open |
| E Replay + safe healing | Partial — 4-app healing matrix + taxonomy + contract; production suite open |
| F a11y/visual/perf/security/locale | Partial — Chromium/Firefox/WebKit suite + artifact manifest; hosted multi-browser CI open |
| G Postgres/Redis/MinIO/RBAC/tenancy | Partial — live PG/Redis/MinIO + dual-tenant OIDC ACL + review pack (unsigned) |
| H Ops/observability/DR | Partial — multi-store DR + failover RTO + paging + on-call contract; hosted multi-region open |
| I React/TS enterprise dashboard | Partial — `/dashboard/` + loopback OIDC PKCE + hosted IdP contract; hosted IdP SSO open |
| J Owned demo-store seeded-defect benchmark | Strong fixtures — Demo 6/6 + Classic 3/3 + Admin 7/7 + Travel 6/6 mutations; third-party open |

## 5. Explicit gaps blocking gate completion (hard opens)

1. Live hosted multi-region DR / on-call paging
2. Live hosted IdP Studio SSO login + multi-tenant ACLs
3. Production / third-party failure matrix + healing suite
4. Broad multi-device CI Appium product-matrix artifacts
5. Broad hosted multi-browser portfolio CI artifacts
6. Independent security/reliability review sign-off

## 6. Next engineering action (Phase 1)

1. Keep offline suite green on this branch (including replay alignment fix).
2. Create controlled local demo-store fixture with documented routes + seeded defects.
3. Run bounded URL→report twice; store screenshots/traces/coverage unknowns.
4. Update issue #22 with commit SHA, CI URL, and artifact paths — only for verified items.

## 7. Definition used here

- **Present:** file/module exists and has some tests or call sites.
- **Partial:** present but missing durable integration, live evidence, or gate criteria.
- **Not established:** required enterprise/benchmark capability absent from the tree or unverified.
