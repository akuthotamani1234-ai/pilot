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

### Gap fixes in progress
- **`cart_total` miss (confirmed):** journey budget (`LARGE=20`) let short “Shop on” cases crowd out the `change_cart` shopping journey. Fix: emit product/`change_cart` journey first (`backend/agents/test_design.py`) + `tests/test_journey_budget_cart_total.py`. Re-benchmark required.
- **Quantity false alarm:** DemoStore accepts qty=2 correctly in isolation; likely shared-session/cart races across workers. Still open.

## Next

Re-run DemoStore accuracy after the journey-budget fix; then tackle quantity isolation if the false alarm remains.
