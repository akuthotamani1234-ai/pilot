# Qpilot X — Phase 1 controlled DemoStore benchmark

**Date:** 2026-11-18  
**Branch:** `cursor/qpilot-x-phase0-baseline-f72b`  
**Fixture entry:** `fixtures/demo_store/`  
**Implementation:** `tests/demo_store.py` + `tests/demo_store_truth.json`  
**Artifacts:** `deep_validation/live_runs/phase1_demo_store_*.json` (committed when present)

## Method

```bash
.venv/bin/python -m tests.accuracy_benchmark --site demo --mode first \
  --out deep_validation/live_runs/phase1_demo_store_run1.json
```

Rules-only (`LLM_PROVIDER=none`), headless Chromium, owned local shop, clean then buggy.

## Run 1 results (2026-11-18)

| Mode | Pages | Features detected | Correct | False alarms | Bugs caught |
|---|---|---|---|---|---|
| clean | 18/18 | 24/24 | 20/24 | 1 | n/a |
| buggy | 18/18 | 23/24 | — | 1 | **5/6** (`cart_total` not tested) |

- Discovery includes scroll-only `/weekend` and action-revealed `/compare`.
- `/admin` classified inaccessible (403).
- False alarm: quantity add-to-cart case `TC-7E74C4E3` (quantity stayed 1 when expecting +2).
- No false passes on planted bugs that were tested.

## Run 2 results (repeatability)

Same command → `phase1_demo_store_run2.json`. Metrics matched run 1 exactly (including the quantity false alarm and `cart_total` not-tested). Gaps are stable, not flaky.

## Gate J

**Partial evidence recorded; gate not closed.**

### Gap fixes
- **`cart_total` miss — fixed & verified:** journey budget crowding. After reorder, run3 (`phase1_demo_store_run3_after_cart_fix.json`) catches **6/6** seeded bugs including `cart_total` (shopping journey failed as expected: cart total stayed 198 when quantity increased).
- **Quantity false alarm — still open:** run3 still has 1 false alarm (`TC-7E74C4E3`). DemoStore accepts qty=2 in isolation; likely shared-session/cart races.

## Run 3 (after journey-budget fix)

| Mode | Pages | Features correct | False alarms | Bugs |
|---|---|---|---|---|
| clean | 18/18 | 21/24 | 1 | n/a |
| buggy | 18/18 | 10/10 judged | 1 | **6/6** |

## Next

Isolate cart-mutating tests / sessions to clear the quantity false alarm before closing Gate J.
