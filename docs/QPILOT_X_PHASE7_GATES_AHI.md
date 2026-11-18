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
- Studio sidebar **Blueprint TODO** (`frontend/chat.html` / `chat.js`) reads `/api/v1/blueprint/progress` (also nested under enterprise readiness)
- Shows gates A–J with done/strong/partial/active/open badges plus upcoming work
- Not a React/TS dashboard — Studio remains HTML/JS

## Gate F / G increments (this pass)
- `backend/portfolio_capture.py` writes a11y/perf/security evidence from discovery `app_map`
- Wired at end of discovery and before portfolio evaluation in `apply_run`
- `backend/audit_store.py` persists studio `_audit` events into SQLite `audit_events`
- `/api/audit/events` lists newest rows

## Tests
- `tests/test_discovery_graph.py`
- `tests/test_ops_readiness.py`
- `tests/test_blueprint_progress.py`
- `tests/test_portfolio_capture.py`
- `tests/test_audit_store.py`
- extended `tests/test_apply_run.py`, `tests/test_server.py`
