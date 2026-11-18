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
| A01 Swarm protocol | `backend/swarm_protocol.py`, `backend/swarm.py`, tests | Partial — threaded workers + protocol; not durable distributed queue |
| A02 Explore scoring | `backend/explore_score.py` | Partial |
| A03 Coverage verifier | `backend/coverage_verify.py` | Partial |
| A04 Oracles | `backend/oracle.py`, `backend/qa_oracles.py` | Partial |
| A05 Data lifecycle | `backend/data_lifecycle.py`, `tests/test_data_lifecycle.py` | Partial |
| A06 Identity/sessions | `backend/auth.py`, Android account helpers | Partial |
| A07 Env virtualization | `backend/env_controls.py` | Partial |
| A08 Deterministic replay | `backend/replay_pack.py`, replay truth tests | Partial — evidence vs execution semantics improved |
| A09 Mutation scoring | `backend/mutation_score.py` | Partial |
| A10 Cross-platform journeys | `backend/journey_map.py` | Partial |
| A11 Localization | `backend/locale_check.py` | Partial |
| A12 Agent evaluation | `backend/agent_eval.py` | Partial |
| A13 Incremental discovery | `backend/incremental_map.py` | Partial |
| A14 Dependency faults | `backend/dependency_fault.py` | Partial |
| A15 Schema evolution | `backend/qa_contracts.py` / assert helpers | Partial / needs deeper wiring audit |
| A16 Human review | `backend/human_review.py` | Partial |
| A17 Quality trends | referenced via `backend/capabilities.py` | Partial |
| A18 Plugin SDK | `backend/plugins.py` | Partial |

## 4. Acceptance gates A–J (current)

Copied from `FINAL_ACCEPTANCE_GATES.md` and confirmed against tree:

| Gate | Status |
|---|---|
| A Discovery completeness | Partial; no controlled live benchmark artifacts yet |
| B Durable swarm | Partial; protocol/workers present |
| C Oracles + fixture cleanup | Partial |
| D Web/API/Android surfaces | Partial; device matrix unverified |
| E Replay + safe healing | Partial |
| F a11y/visual/perf/security/locale | Partial |
| G Postgres/Redis/MinIO/RBAC/tenancy | **Not established** |
| H Ops/observability/DR | **Not established** |
| I React/TS enterprise dashboard | Partial; Studio is HTML/JS, not React |
| J Owned demo-store seeded-defect benchmark | **Partial** — fixture + two URL→report runs recorded; see `docs/QPILOT_X_PHASE1_BENCHMARK.md` |

## 5. Explicit gaps blocking later phases

1. No owned `fixtures/demo_store` (or equivalent) with seeded defects and ground-truth routes.
2. No PostgreSQL / Redis / object-store deployment path in-repo for enterprise mode.
3. No durable leased task queue with crash recovery beyond in-process swarm helpers.
4. Frontend is Studio HTML/JS (`frontend/`), not the proposed React/TypeScript apps tree.
5. Live URL→report benchmark and Android device-matrix evidence not recorded for `final`.
6. Issue #22 Phase 1+ boxes remain unchecked (verification rule: code ≠ done).

## 6. Next engineering action (Phase 1)

1. Keep offline suite green on this branch (including replay alignment fix).
2. Create controlled local demo-store fixture with documented routes + seeded defects.
3. Run bounded URL→report twice; store screenshots/traces/coverage unknowns.
4. Update issue #22 with commit SHA, CI URL, and artifact paths — only for verified items.

## 7. Definition used here

- **Present:** file/module exists and has some tests or call sites.
- **Partial:** present but missing durable integration, live evidence, or gate criteria.
- **Not established:** required enterprise/benchmark capability absent from the tree or unverified.
