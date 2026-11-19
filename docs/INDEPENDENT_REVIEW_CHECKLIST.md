# Gate G — independent security / reliability review checklist

This checklist is **not** a completed review. An independent reviewer (not the
implementing agent) must sign each row with date + evidence links before Gate G
or issue #22 Phase 7 review boxes can close.

## Scope

| Area | What to verify | Evidence pointers |
|---|---|---|
| AuthN/Z | Dashboard auth modes; OIDC JWT path; tenant ACL denials audited | `docs/ops-evidence/dashboard_auth_matrix_drill.json`, `loopback_sso_drill.json`, `sso_tenant_acl_drill.json`, audit export |
| Secrets | No committed `.env`; redaction via `backend/safety.py` | repo scan + `SECURITY.md` |
| Tenancy | Postgres + SQLite isolation; cross-tenant deny | `pg_tenancy_drill.json`, `postgres_isolation_drill.json` |
| Queue | Redis/SQLite DurableQueue leases + cancel/retry | `redis_*`, `swarm_*` drills |
| Object store | MinIO put/get + backup/restore | `minio_*` drills |
| DR | SQLite / MinIO / Postgres isolated restore + dual-region failover | `backup_restore_drill.json`, `minio_backup_restore_drill.json`, `postgres_dr_drill.json`, `multi_region_dr_drill.json` |
| Ops | Incident runbook + paging / escalation (hosted on-call still open) | `docs/INCIDENT_RUNBOOK.md`, `paging_rehearsal.json`, `paging_escalation_drill.json` |
| Evidence pack | SHA-256 inventory of all ops-evidence JSON (unsigned) | `independent_review_pack.json` |
| Review readiness | Checklist + pack + blockers inventory scored (unsigned) | `independent_review_readiness_drill.json` |
| Review summary | Human-readable Markdown summary for reviewers (unsigned) | `INDEPENDENT_REVIEW_SUMMARY.md` |
| Review request | Reviewer handoff receipt (unsigned; starts human sign-off) | `independent_review_request_drill.json` |
| Review integrity | SHA-256 integrity over checklist/pack/blockers (unsigned) | `independent_review_integrity_drill.json` |
| Android | Appium product matrix honesty (API26+; API24 smoke separate) | `android_appium_product_matrix_drill.json` |
| Portfolios | Multi-browser suite does not over-claim Gate F complete | `multi_browser_portfolio_suite_drill.json` |

## Sign-off (blank until independent review)

| Reviewer | Date | Commit SHA | Verdict | Notes |
|---|---|---|---|---|
| _pending_ |  |  |  | Hosted IdP SSO + multi-region on-call still open |

## Rule

Do **not** mark `G-review` done in Studio sidebar or issue #22 until this table
has a non-agent human/independent reviewer entry.
