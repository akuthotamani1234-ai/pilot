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

## Rule

Do not mark Gate H complete in `FINAL_ACCEPTANCE_GATES.md` or issue #22 until each row above has a dated evidence artifact and an independent review notes the drill.
