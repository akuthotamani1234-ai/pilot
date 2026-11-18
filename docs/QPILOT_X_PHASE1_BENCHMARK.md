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
- **`cart_total` miss — fixed & verified (run3):** journey-budget reorder; **6/6** seeded bugs.
- **Quantity false alarm — fixed & verified (run4):** clear leftover cart lines + qty input before measuring; **0 false alarms**, bugs still **6/6**.

## Run 3 (after journey-budget fix)

| Mode | Pages | Features correct | False alarms | Bugs |
|---|---|---|---|---|
| clean | 18/18 | 21/24 | 1 | n/a |
| buggy | 18/18 | 10/10 judged | 1 | **6/6** |

## Run 4 (after quantity isolation)

| Mode | Pages | Features correct | False alarms | Bugs |
|---|---|---|---|---|
| clean | 18/18 | **23/24** | **0** | n/a |
| buggy | 18/18 | 10/10 judged | **0** | **6/6** |

Remaining clean gap after run4: `orders.tracking` not tested (journey-budget crowding). Fixed by Phase 2 priority reorder; **verified in run5**.

## Run 5 (after orders journey priority — 2026-11-18)

| Mode | Pages | Features correct | False alarms | Bugs |
|---|---|---|---|---|
| clean | 18/18 | **24/24** | **0** | n/a |
| buggy | 18/18 | 10/10 judged | **0** | **6/6** |

Artifact: `deep_validation/live_runs/phase1_demo_store_run5_orders_tracking.json`.  
`orders.tracking` now tested + verified (`TC-9C3AE640`). Gate J DemoStore seeded-defect evidence is strong; broader third-party sites and live Android remain out of scope for this fixture.

## Run 6 (Gate A surface page `/lab`)

DemoStore public `/lab` (same-site iframe + open shadow root); truth pages **19**.

| Mode | Pages | Features correct | False alarms | Bugs |
|---|---|---|---|---|
| clean | **19/19** | **24/24** | **0** | n/a |
| buggy | **19/19** | 10/10 judged | **0** | **6/6** |

Artifact: `deep_validation/live_runs/phase1_demo_store_run6_lab_surfaces.json`.

## Run 7 (remeasure after Gates H/I/D offline slice — 2026-11-18)

Repeat of controlled DemoStore `accuracy_benchmark --mode first` on this phase branch.

| Mode | Pages | Features correct | False alarms | Bugs |
|---|---|---|---|---|
| clean | **19/19** | **24/24** | **0** | n/a |
| buggy | **19/19** | 10/10 judged | **0** | **6/6** |

Artifacts: `deep_validation/live_runs/phase1_demo_store_run7.json` + `phase1_demo_store_run7_summary.json`.  
Gate J DemoStore evidence remains **strong**; broader third-party sites and live Android still open.
