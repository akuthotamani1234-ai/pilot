# Qpilot X — Gate A / H / I increments (post Phase 7 status)

**Date:** 2026-11-18  
**Branch:** `cursor/qpilot-x-phase0-baseline-f72b`

## Gate A
- `backend/discovery_graph.py` writes `discovery_graph.json` with schema version + provenance on every node/edge
- Wired from `discovery_report` and `apply_run`
- `gate_a_complete` stays **false**

## Gate H
- `backend/ops_readiness.py` + `/api/ops/readiness` (+ nested under enterprise readiness)
- CI/docs presence vs missing observability, backup/restore, load tests
- `gate_h_complete` stays **false**

## Gate I
- Studio sidebar **Blueprint TODO** (`frontend/chat.html` / `chat.js`) reads `/api/v1/blueprint/progress`
- React/TypeScript dashboard scaffold: `frontend/dashboard` served at `/dashboard/`
- Auth, approvals UX, and hosted multi-tenant contracts still open — `gate_i_complete` stays false

## Gate C / E / F increments
- `apply_run` writes `oracle_decisions.json`, confirmed `lifecycle.json`, `healing_policy.json`
- `backend/visual_capture.py` records first-run screenshot evidence when pixel diff has not run
- Portfolio capture remains wired from discovery + apply_run

## Tests
- `tests/test_discovery_graph.py`
- `tests/test_ops_readiness.py`
- `tests/test_blueprint_progress.py`
- `tests/test_portfolio_capture.py`
- `tests/test_audit_store.py`
- `tests/test_healing_policy.py`
- `tests/test_visual_capture.py`
- extended `tests/test_apply_run.py`, `tests/test_server.py`, `tests/test_enterprise_phase6.py`
