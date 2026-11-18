# Gate H — ops drill checklist (not complete)

This checklist documents what must be proven before Gate H can leave **Partial / not established**.  
**Having this file does not complete Gate H.**

## Required evidence (all still open unless linked)

| Drill | Status | Evidence link |
|---|---|---|
| Observability (metrics + traces + alerts) | Partial (local snapshot only) | `docs/ops-evidence/local_metrics_snapshot.json` — central stack still open |
| Backup of run store / object store | Partial (local SQLite only) | `docs/ops-evidence/backup_restore_drill.json` — object-store DR still open |
| Restore from backup into an isolated env | Partial (local folder restore) | same drill artifact — live isolated env still open |
| Load / soak against a controlled fixture | Open | — |
| Incident runbook tabletop | Open | — |
| CI deploy + rollback rehearsal | Open | — |

## Local foundations already present

- CI workflow: `.github/workflows/blow-ai.yml`
- Deploy notes: `DEPLOYMENT.md`
- Security reporting: `SECURITY.md`
- Probe: `backend/ops_readiness.py` + `/api/ops/readiness` (never sets `gate_h_complete`)

## Rule

Do not mark Gate H complete in `FINAL_ACCEPTANCE_GATES.md` or issue #22 until each row above has a dated evidence artifact and an independent review notes the drill.
