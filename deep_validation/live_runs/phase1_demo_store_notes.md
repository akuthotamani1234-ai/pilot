# Phase 1 — DemoStore URL→report benchmark notes

**Date:** 2026-11-18  
**Branch:** `cursor/qpilot-x-phase0-baseline-f72b`  
**Fixture:** `fixtures/demo_store` → `tests/demo_store.py` + `tests/demo_store_truth.json`  
**Command:** `.venv/bin/python -m tests.accuracy_benchmark --site demo --mode first --out deep_validation/live_runs/phase1_demo_store_run1.json`  
**Duration:** ~11.9 minutes (clean + buggy)

## Run 1 summary

| Mode | Pages | Features detected | Correct | False alarms | Bugs |
|---|---|---|---|---|---|
| clean | 18/18 | 24/24 | 20/24 | 1 | n/a |
| buggy | 18/18 | 23/24 | 9/10 (feature rows) | 1 | **5/6 caught** |

### Discovery
- All known routes found, including scroll-only `/weekend` and action-revealed `/compare`.
- `/admin` correctly classified inaccessible (403).

### Seeded defects
- Caught: `dead_button`, `qty_below_min`, `search_wrong_hit`, `sort_price`, `wishlist_error`
- Not tested: `cart_total` (gap — no executed assertion covering planted cart-total defect)
- False passes: none

### Known false alarm (both modes)
`TC-7E74C4E3` quantity add-to-cart assertion failed on a clean/buggy shop:
cart quantity stayed `1 -> 1` when expecting +2. Treat as product/test defect to investigate in Phase 2/4 (oracle/assertion strength), not as Gate J complete.

### Coverage unknowns / incomplete feature outcomes
Clean mode: 4 features not fully “correct” under truth scoring (20/24 correct). Exact row IDs are in `phase1_demo_store_run1.json`.

## Safety
Protected actions: no evidence of Place order / Buy now / logout execution in this benchmark’s never-requested check (see JSON `never_requested_but_done`).

## Repeatability (run 2)

Command identical; artifact: `phase1_demo_store_run2.json` (~11.9 minutes).

| Metric | Run 1 | Run 2 |
|---|---|---|
| clean pages | 18/18 | 18/18 |
| clean features detected/correct | 24/24 · 20/24 | 24/24 · 20/24 |
| clean false alarms | 1 | 1 |
| buggy bugs caught | 5/6 | 5/6 |
| buggy not_tested | `cart_total` | `cart_total` |
| buggy false passes | 0 | 0 |

The quantity false alarm and `cart_total` miss reproduced — treat as stable gaps, not flakes.

## Gate J status
**Partial evidence recorded; gate not closed.** Owned fixture URL→report works twice with stable measured gaps. Still required before closing Gate J:
1. Root-cause or accept-with-unknown `cart_total` miss
2. Root-cause or fix quantity false alarm `TC-7E74C4E3` with regression
3. Link issue #22 with commit SHA + artifact paths
