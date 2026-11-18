# Gate H — incident runbook (tabletop draft)

This is a **local operator draft**. It does **not** complete Gate H.
A dated tabletop with roles, paging, and restore proof is still required.

## Severity

| Level | Meaning | First response |
|---|---|---|
| SEV1 | Studio down / cannot start runs / data loss risk | Stop writers, capture logs, restore from last known-good backup |
| SEV2 | Partial feature failure (queue stuck, dashboard 5xx) | Isolate blast radius, drain or restart local services, file audit note |
| SEV3 | Degraded UX / non-blocking errors | Log, schedule fix, no emergency restore |

## First 15 minutes

1. Confirm blast radius (one workstation vs shared host).
2. Capture: UI port, `runs/` last modified, `artifacts/ops/` drill timestamps, recent audit events.
3. If SQLite run store is suspect: run local backup/restore drill (`POST /api/ops/drills/backup-restore`) into an isolated folder; do not overwrite production paths.
4. If approvals/auth misbehave: unset `QPILOT_DASHBOARD_TOKEN` only on the affected local Studio, then re-set after recovery.
5. Record incident notes under `docs/ops-evidence/` when a real drill happens (date, operator, outcome).

## Communication

- Local Studio: notify the tester who owns the machine.
- Shared/hosted deploy (not supported yet): page on-call — **hosting path still open for Gate H/I**.

## Exit criteria for Gate H (still unmet)

- [ ] Dated tabletop with named roles
- [ ] Live restore into an isolated environment
- [ ] Load/soak against a controlled fixture beyond the local API probe
- [ ] Paging / alert path proven (loopback rehearsal only so far — `docs/ops-evidence/paging_rehearsal.json`)
