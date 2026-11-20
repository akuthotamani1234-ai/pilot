# Controlled demo store (Phase 1 benchmark fixture)

Owned local e-commerce fixture used for Qpilot X Gate J / Phase 1.

## Canonical implementation

| Asset | Path |
|---|---|
| HTTP shop server | `tests/demo_store.py` |
| Ground-truth routes/features/bugs | `tests/demo_store_truth.json` |
| Accuracy harness | `tests/accuracy_benchmark.py` |
| Slow acceptance tests | `tests/test_accuracy.py` |

Do not invent a second store. This folder holds the Phase 1 **manifest and evidence pointers** so blueprint
`fixtures/demo_store` maps to the existing owned fixture.

## How to start manually

```bash
.venv/bin/python tests/demo_store.py 8766          # clean shop
.venv/bin/python tests/demo_store.py 8766 bugs     # six planted defects
```

Open `http://127.0.0.1:8766`. Account: `demo@store.test` / `Store#2024`.

## Seeded defects (bugs=True)

1. `sort_price` — Price low→high sort is wrong  
2. `cart_total` — cart total ignores quantity  
3. `search_wrong_hit` — search returns non-matching items  
4. `qty_below_min` — quantity minus goes below 1  
5. `wishlist_error` — Add to wishlist shows an error  
6. `dead_button` — Notify me does nothing  

## Benchmark command

```bash
.venv/bin/python -m tests.accuracy_benchmark --site demo --mode first \
  --out deep_validation/live_runs/phase1_demo_store_run1.json
```

Repeat once for flakiness and write `phase1_demo_store_run2.json`. Record coverage unknowns in
`deep_validation/live_runs/phase1_demo_store_notes.md`.

## Safety

Protected actions must never execute: Place order, Buy now, Log out, and the `never` list in the truth file.
