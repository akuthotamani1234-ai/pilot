# Qpilot X — Phase 3 durable swarm

**Date:** 2026-11-18  
**Branch:** `cursor/qpilot-x-phase0-baseline-f72b`

## Gap before this phase

Existing `swarm_protocol.Lease` is in-memory only. Blueprint Gate B requires durable leases, retries, cancellation, checkpoints, and duplicate-delivery safety.

## Delivered (local-first)

| Piece | Module |
|---|---|
| Durable SQLite task store | `backend/swarm_queue.py` |
| Supervisor plan/enqueue/drain | `backend/swarm_supervisor.py` |
| Tests: idempotent enqueue, exclusive lease, heartbeat, expiry recovery, retries, checkpoint, cancel | `tests/test_swarm_queue.py` |
| Supervisor drain + crash retry | `tests/test_swarm_supervisor.py` |

### Behaviors covered
- Typed task rows with attempt counters and idempotency keys
- Claim/lease with heartbeat extension
- Expired lease → `retry_wait` (or `failed` when attempts exhausted)
- Transient vs permanent failure classes
- Checkpoint persistence while leased
- Duplicate complete ack is safe
- Cancel prevents further claims
- Checkout/payment URLs never scheduled as workers

## Pipeline wiring (this branch)
- `backend/swarm_evidence.record_swarm` plans + drains the durable queue over crawled URLs
- Called at end of discovery and as a fallback in `apply_run`
- Writes `swarm_evidence.json` + per-run `swarm_queue.sqlite`
- Payment/checkout URLs still never scheduled as workers

## Not yet Gate B complete
- Redis/Postgres enterprise queue backend
- Full LangGraph wiring of every specialist agent through DurableQueue
- Live multi-worker crash drill artifacts linked in issue #22

## Next
Keep this queue as the swarm substrate while closing Redis/Postgres and live crash drills.
