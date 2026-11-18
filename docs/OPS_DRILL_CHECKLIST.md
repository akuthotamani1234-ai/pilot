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
| Incident runbook tabletop | Partial (draft + offline cross-check) | `docs/INCIDENT_RUNBOOK.md` + `docs/ops-evidence/incident_tabletop_drill.json` — live hosted paging still open |
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
| B | `/api/ops/drills/swarm-control`, `swarm-retry` | `docs/ops-evidence/swarm_control_drill.json`, `swarm_retry_drill.json` |
| C | `/api/ops/drills/lifecycle-cleanup`, `admin-portal-lifecycle`, `oracle-spec`, `demo-store-cart-lifecycle` | `docs/ops-evidence/lifecycle_cleanup_drill.json`, `admin_portal_lifecycle_drill.json`, `oracle_spec_drill.json`, `demo_store_cart_lifecycle_drill.json` |
| D | `/api/ops/drills/device-matrix`, `android-emulator-smoke`, `android-appium-product-matrix`, `android-adb-probe` | `docs/ops-evidence/device_matrix_drill.json`, `android_emulator_smoke_drill.json`, `android_appium_product_matrix_drill.json`, `android_adb_probe.json`, `android_appium_ci_contract.json` |
| E | `/api/ops/drills/failure-matrix`, `healing-regression`, `demo-store-healing-live` | `docs/ops-evidence/failure_matrix_drill.json`, `healing_regression_drill.json`, `demo_store_healing_live_drill.json` |
| F | `/api/ops/drills/locale-portfolio`, `security-portfolio`, `a11y-portfolio`, `perf-portfolio`, `visual-portfolio`, `compatibility-portfolio`, `multi-browser-portfolio-suite` | `docs/ops-evidence/{locale,security,a11y,perf,visual,compatibility}_portfolio_drill.json`, `multi_browser_portfolio_suite_drill.json` |
| G | Postgres/Redis/MinIO + `/api/audit/export` + `/api/ops/drills/audit-export` | `docs/ops-evidence/pg_tenancy_drill.json`, `audit_export_drill.json` (+ infra drills) |
| I | `/api/ops/drills/api-version-contract`, `dashboard-auth-matrix`, `approvals`, `sso-contract`, `loopback-sso` | `docs/ops-evidence/api_version_contract.json`, `dashboard_auth_matrix_drill.json`, `approvals_drill.json`, `sso_contract_drill.json`, `loopback_sso_drill.json` |

Studio sidebar Blueprint TODO (`/api/v1/blueprint/progress`) lists done vs open upcoming items for these increments.

## Rule

Do not mark Gate H complete in `FINAL_ACCEPTANCE_GATES.md` or issue #22 until each row above has a dated evidence artifact and an independent review notes the drill.
