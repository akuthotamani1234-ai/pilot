# Qpilot X — Phase 6 enterprise foundations

**Date:** 2026-11-18  
**Branch:** `cursor/qpilot-x-phase0-baseline-f72b`

## What landed (offline, local-first)

| Blueprint need | Change |
|---|---|
| RBAC / tenant isolation | `backend/rbac.py` — deny-by-default roles + audit event helper |
| API versioning | `backend/api_versioning.py` — `/api/v1` canonical; legacy `/api` → v1 |
| Object storage | `backend/object_store.py` — local filesystem store; remote MinIO URI stays unready until wired |
| Readiness probe | `backend/enterprise.py` — never marks Gate G/I complete while Postgres/Redis/React missing |
| Config knobs | `.env.example` optional `POSTGRES_URL`, `REDIS_URL`, `OBJECT_STORE_URI` |

## Later increments
- `migrations/001_tenancy.sql` + `backend/migrate.py` (SQLite apply offline; Postgres URI stays unready)
- Queue backend selector + swarm supervisor wiring
- Readiness lists schema migration files without auto-applying on every probe

## Explicitly not done

- No live Postgres migrations / Redis queue swap / MinIO deployment
- Studio UI remains HTML/JS (`frontend/`); React/TypeScript dashboard **not** established
- No claim that configuring a URL alone makes Gate G ready

## Tests
- `tests/test_enterprise_phase6.py`
- `tests/test_migrate.py`
