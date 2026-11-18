# Gate H — ops drill checklist (not complete)

This checklist documents what must be proven before Gate H can leave **Partial / not established**.  
**Having this file does not complete Gate H.**

## Required evidence (all still open unless linked)

| Drill | Status | Evidence link |
|---|---|---|
| Observability (metrics + traces + alerts) | Partial (local snapshot only) | `docs/ops-evidence/local_metrics_snapshot.json` — central stack still open |
| Backup of run store / object store | Partial (SQLite + MinIO object copy) | `docs/ops-evidence/backup_restore_drill.json` + `docs/ops-evidence/minio_backup_restore_drill.json` — hosted DR still open |
| Restore from backup into an isolated env | Partial (local folder + MinIO restore-to-key) | same artifacts — live isolated env still open |
| Load / soak against a controlled fixture | Partial (local API probe + AdminPortal soak) | `docs/ops-evidence/local_load_probe.json` + `docs/ops-evidence/controlled_soak_drill.json` — hosted/prod-like load still open |
| Incident runbook tabletop | Partial (draft + stub only) | `docs/INCIDENT_RUNBOOK.md` + `docs/ops-evidence/incident_tabletop_stub.json` — live paging still open |
| CI deploy + rollback rehearsal | Partial (offline rehearsal only) | `docs/ops-evidence/ci_rollback_rehearsal.json` — live hosted rollback still open |
| Paging / alert path | Partial (loopback sink only) | `docs/ops-evidence/paging_rehearsal.json` — live hosted on-call still open |

## Local foundations already present

- CI workflow: `.github/workflows/blow-ai.yml`
- Deploy notes: `DEPLOYMENT.md`
- Security reporting: `SECURITY.md`
- Probe: `backend/ops_readiness.py` + `/api/ops/readiness` (never sets `gate_h_complete`)
- Gate D ADB probe: `POST /api/ops/drills/android-adb-probe` → `docs/ops-evidence/android_adb_probe.json` (ADB may be present with zero devices; does not complete Gate D)

## Cross-gate offline drills (still Partial; do not over-claim)

| Gate | Drill API | Evidence |
|---|---|---|
| A | `/api/ops/drills/admin-portal-surfaces`, `demo-store-surfaces`, `classic-shop-surfaces`, `travel-site-surfaces` | `docs/ops-evidence/*_surface_coverage.json` |
| B | `/api/ops/drills/swarm-control` | `docs/ops-evidence/swarm_control_drill.json` |
| C | `/api/ops/drills/lifecycle-cleanup` | `docs/ops-evidence/lifecycle_cleanup_drill.json` |
| D | `/api/ops/drills/device-matrix` | `docs/ops-evidence/device_matrix_drill.json` |
| E | `/api/ops/drills/failure-matrix`, `healing-regression` | `docs/ops-evidence/failure_matrix_drill.json`, `healing_regression_drill.json` |
| F | `/api/ops/drills/locale-portfolio`, `security-portfolio`, `a11y-portfolio`, `perf-portfolio`, `visual-portfolio` | `docs/ops-evidence/{locale,security,a11y,perf,visual}_portfolio_drill.json` |
| G | Postgres/Redis/MinIO + `/api/audit/export` | `docs/ops-evidence/pg_tenancy_drill.json` (+ infra drills) |
| I | `/api/ops/drills/api-version-contract` | `docs/ops-evidence/api_version_contract.json` |

Studio sidebar Blueprint TODO (`/api/v1/blueprint/progress`) lists done vs open upcoming items for these increments.

## Rule

Do not mark Gate H complete in `FINAL_ACCEPTANCE_GATES.md` or issue #22 until each row above has a dated evidence artifact and an independent review notes the drill.
