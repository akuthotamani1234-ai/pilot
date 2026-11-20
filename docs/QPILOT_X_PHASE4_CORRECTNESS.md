# Qpilot X — Phase 4 correctness increments

**Date:** 2026-11-18  
**Branch:** `cursor/qpilot-x-phase0-baseline-f72b`

## Gaps addressed

| Blueprint need | Change |
|---|---|
| Trusted oracles with provenance | `oracle.bind_assertion` / `decide_observation` — AI stays `needs_review`; approved sources can pass/fail with oracle_source |
| Real fixture cleanup proof | `Lifecycle.cleanup_confirmed(remote_delete=...)` — local cleaned only after remote confirms; failures reported |
| Replay execution truth | Already landed in Phase 0 (`replay_pack.run_saved`) |
| Guarded healing | Existing self-healing already rejects assertion edits; no weaken |

## Tests
- `tests/test_oracle_provenance.py`
- `tests/test_lifecycle_remote_cleanup.py`

## Gate C / E status
Still **Partial**, with deeper wiring on this branch:
- Durable lifecycle state (`qx_lifecycle_state.json`) shared across prepare/finish
- Finish cleanup confirms via `created.jsonl` (synthetic unused rows get `synthetic_unused:` proof, not a fake remote delete)
- Design-time `oracle_bind.attach_assertions`; failure analysis softens unaccepted AI oracles away from `product_defect`
- Analysis attempts bounded `run_saved` (limit 3) when packages + scripts exist

Live portal/API cleanup adapters per fixture backend and a full failure-reproduction matrix remain open.
