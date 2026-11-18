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
Still **Partial**: provenance + confirmed cleanup APIs exist with unit proof. Full wiring through every run path and live cleanup adapters for each fixture backend remain open.
