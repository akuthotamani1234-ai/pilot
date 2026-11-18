# Gate B — product-wide durable swarm review checklist

This checklist is **not** a completed review. Product-wide Redis DurableQueue
adoption across all discovery/apply paths must be signed by an independent
reviewer before Gate B can leave Partial.

## Scope

| Area | What to verify | Evidence pointers |
|---|---|---|
| Queue backend | `REDIS_URL` preferred; SQLite fallback honest | `redis_durable_queue_drill.json`, `swarm_redis_default.json` |
| Leases | Exclusive claim + expiry → retry_wait | `redis_lease_drill.json`, `swarm_retry_drill.json` |
| Control | claim / checkpoint / cancel | `swarm_control_drill.json` |
| Specialists | coverage + oracle roles planned/drained | `qx_core_capabilities_drill.json` (A01) |
| Multi-region | Redis dual-DB failover (local only) | `redis_multi_region_drill.json` |
| Product wiring | discovery/apply dual-write into DurableQueue | code review of `swarm_supervisor` + `server` plan/drain |

## Sign-off (blank until independent review)

| Reviewer | Date | Commit SHA | Verdict | Notes |
|---|---|---|---|---|
| _pending_ |  |  |  | Product-wide Redis swarm review still open |

## Rule

Do **not** mark Gate B complete or issue #22 Phase 3 boxes done until this
table has a non-agent human/independent reviewer entry.
