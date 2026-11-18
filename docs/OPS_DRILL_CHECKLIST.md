# Gate H — ops drill checklist (not complete)

This checklist documents what must be proven before Gate H can leave **Partial / not established**.  
**Having this file does not complete Gate H.**

## Required evidence (all still open unless linked)

| Drill | Status | Evidence link |
|---|---|---|
| Observability (metrics + traces + alerts) | Partial (local snapshot + readiness probe) | `docs/ops-evidence/local_metrics_snapshot.json` + `observability_probe_drill.json` — central stack still open |
| Backup of run store / object store | Partial (SQLite + MinIO object copy + Postgres dump) | `docs/ops-evidence/backup_restore_drill.json` + `minio_backup_restore_drill.json` + `postgres_dr_drill.json` + `multi_region_dr_drill.json` — hosted multi-region DR still open |
| Restore from backup into an isolated env | Partial (local folder + MinIO restore-to-key + isolated Postgres DB + dual-region failover) | same artifacts — hosted isolated env still open |
| Load / soak against a controlled fixture | Partial (local API probe + AdminPortal soak) | `docs/ops-evidence/local_load_probe.json` + `docs/ops-evidence/controlled_soak_drill.json` — hosted/prod-like load still open |
| Incident runbook tabletop | Partial (draft + offline cross-check) | `docs/INCIDENT_RUNBOOK.md` + `docs/ops-evidence/incident_tabletop_drill.json` — live hosted paging still open |
| CI deploy + rollback rehearsal | Partial (offline rehearsal only) | `docs/ops-evidence/ci_rollback_rehearsal.json` — live hosted rollback still open |
| Paging / alert path | Partial (loopback sink + primary→secondary escalation) | `docs/ops-evidence/paging_rehearsal.json` + `paging_escalation_drill.json` — live hosted on-call still open |

## Local foundations already present

- CI workflow: `.github/workflows/blow-ai.yml`
- Deploy notes: `DEPLOYMENT.md`
- Security reporting: `SECURITY.md`
- Probe: `backend/ops_readiness.py` + `/api/ops/readiness` (never sets `gate_h_complete`)
- Gate D ADB probe: `POST /api/ops/drills/android-adb-probe` → `docs/ops-evidence/android_adb_probe.json` (ADB may be present with zero devices; does not complete Gate D)

## Cross-gate offline drills (still Partial; do not over-claim)

| Gate | Drill API | Evidence |
|---|---|---|
| A | `/api/ops/drills/admin-portal-surfaces`, `demo-store-surfaces`, `classic-shop-surfaces`, `travel-site-surfaces`, `discovery-score` | `docs/ops-evidence/*_surface_coverage.json`, `discovery_score_drill.json` |
| B | `/api/ops/drills/swarm-control`, `swarm-retry`, `redis-swarm-contention` | `docs/ops-evidence/swarm_control_drill.json`, `swarm_retry_drill.json`, `redis_swarm_contention_drill.json` |
| C | `/api/ops/drills/lifecycle-cleanup`, `admin-portal-lifecycle`, `oracle-spec`, `demo-store-cart-lifecycle`, `classic-shop-cart-lifecycle`, `multi-portal-oracle` | `docs/ops-evidence/lifecycle_cleanup_drill.json`, `admin_portal_lifecycle_drill.json`, `oracle_spec_drill.json`, `demo_store_cart_lifecycle_drill.json`, `classic_shop_cart_lifecycle_drill.json`, `multi_portal_oracle_drill.json` |
| D | `/api/ops/drills/device-matrix`, `android-emulator-smoke`, `android-appium-product-matrix`, `multi-api-android-matrix`, `cross-platform-journey`, `android-adb-probe`, `apidemos-interaction`, `device-artifact-manifest`, `hosted-runner-contracts` | `device_matrix_drill.json`, `android_emulator_smoke_drill.json`, `android_appium_product_matrix_drill.json`, `multi_api_android_matrix_drill.json`, `cross_platform_journey_drill.json`, `android_adb_probe.json`, `apidemos_interaction_drill.json`, `android_appium_ci_contract.json`, `multi_device_ci_contract.json`, `device_artifact_manifest_drill.json` |
| E | `/api/ops/drills/failure-matrix`, `healing-regression`, `demo-store-healing-live`, `live-failure-matrix`, `multi-app-healing-suite`, `production-healing-matrix`, `production-healing-taxonomy` | `docs/ops-evidence/failure_matrix_drill.json`, `healing_regression_drill.json`, `demo_store_healing_live_drill.json`, `live_failure_matrix_drill.json`, `multi_app_healing_suite_drill.json`, `production_healing_matrix_drill.json`, `production_healing_taxonomy_drill.json` |
| F | `/api/ops/drills/…-portfolio`, `multi-browser-portfolio-suite`, `portfolio-artifact-manifest`, `hosted-runner-contracts` (+ `multi-browser-portfolios.yml`) | `docs/ops-evidence/{locale,security,a11y,perf,visual,compatibility}_portfolio_drill.json`, `multi_browser_portfolio_suite_drill.json`, `multi_browser_ci_contract.json`, `portfolio_artifact_manifest_drill.json` |
| G | Postgres/Redis/MinIO + audit export + `sso-tenant-acl` + review checklist/pack/readiness | `pg_tenancy_drill.json`, `audit_export_drill.json`, `sso_tenant_acl_drill.json`, `independent_review_checklist.json`, `independent_review_pack.json`, `independent_review_readiness_drill.json` |
| H | + `multi-region-dr`, `minio-multi-region`, `redis-multi-region`, `multi-store-dr`, `failover-rto`, `paging-escalation`, `observability-probe` | `multi_region_dr_drill.json`, `minio_multi_region_drill.json`, `redis_multi_region_drill.json`, `multi_store_dr_drill.json`, `failover_rto_drill.json`, `paging_escalation_drill.json`, `observability_probe_drill.json` |
| I | `/api/ops/drills/api-version-contract`, `dashboard-auth-matrix`, `approvals`, `sso-contract`, `loopback-sso`, `loopback-auth-code-sso`, `loopback-pkce-sso`, `sso-tenant-acl`, `dual-tenant-oidc-acl` | `api_version_contract.json`, `dashboard_auth_matrix_drill.json`, `approvals_drill.json`, `sso_contract_drill.json`, `loopback_sso_drill.json`, `loopback_auth_code_sso_drill.json`, `loopback_pkce_sso_drill.json`, `sso_tenant_acl_drill.json`, `dual_tenant_oidc_acl_drill.json` |

| QX | `/api/ops/drills/qx-capabilities`, `qx-core-capabilities` | `qx_capabilities_drill.json` (A02/A07/A12–A18), `qx_core_capabilities_drill.json` (A01/A03–A06/A08/A11) |
| J | `/api/ops/drills/mutation-score` | `docs/ops-evidence/mutation_score_drill.json` |

Studio sidebar Blueprint TODO (`/api/v1/blueprint/progress`) lists done vs open upcoming items for these increments.

## Rule

Do not mark Gate H complete in `FINAL_ACCEPTANCE_GATES.md` or issue #22 until each row above has a dated evidence artifact and an independent review notes the drill.
