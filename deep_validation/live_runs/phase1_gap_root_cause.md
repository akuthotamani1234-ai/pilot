# Phase 1 gap root-cause (cart_total + quantity false alarm)

**Evidence:** `phase1_demo_store_run{1,2}.json` — both runs identical.

## Gap A — `TC-7E74C4E3` quantity false alarm (clean + buggy)

**Symptom:** After typing quantity `2` and Add to cart, measurement says cart quantity `1 → 1`.

**Manual check (this environment):** DemoStore correctly accepts `qty=2` (cart count becomes 2; line total ₹114). So the shop itself is fine.

**Likely cause:** Shared authenticated DemoStore session across parallel pytest workers.
Cart feature tests use `@pytest.mark.xdist_group("cart")`, but other workers still run journeys/forms that mutate the same server-side cart when they reuse the same login cookie/`sid`. That races `start = in_cart()` vs `got = in_cart()` and produces stable false failures without being “random flake” across full-suite repeats.

**Secondary risk:** `_choose_options` forces the first `<select>` value (Small). Default HTML also selects Small first. Size mismatch with an existing line is less likely here than session races.

**Fix direction (Phase 1/4):**
1. Isolate DemoStore identity per worker (unique email/session or per-worker shop instance), **or**
2. Serialize all cart-mutating tests (journey + quantity + remove) under one xdist group / one worker, **or**
3. Use per-test cart cleanup + assert on delta with retry against stable line id.

## Gap B — seeded `cart_total` not tested (5/6 bugs)

**Symptom:** `bugs.not_tested = ["cart_total"]`. Feature row `cart.totals` has `tested=False` / no matching executed cases; on buggy run `detected=False`.

**Truth expectation:** Feature `cart.totals` (`detect: total`, `test: total`, bug `cart_total`) should be exercised by a case whose failure signature matches `cart total`.

**Confirmed cause:** `builtin_journeys` default `LARGE=20`. Per-product short “Shop on …” journeys were emitted **before** the full `journey=product` case with `change_cart=True`. With ~40 product pages, the budget filled with short add→cart cases; the cart-total shopping journey was never generated (0 `Shopping journey` cases in Phase 1 runs).

Planted `cart_total` only breaks `#cart-total` via `store._total()`; line-total cells stay correct, so short journeys cannot catch it.

**Fix landed & verified (run3):** reorder so the product/`change_cart` shopping journey is emitted before short Shop-on cases (`backend/agents/test_design.py`), with regression `tests/test_journey_budget_cart_total.py`.

Run3 buggy result: **bugs caught 6/6** including `cart_total`. Shopping journey `TC-2EF282F6` failed with signature `should add 141 to the cart total, it went 198 -> 198`.

## Quantity false-alarm fix

**Fix:** quantity feature scripts now remove any existing cart line for the product, clear the qty input, assert `start == 0`, then always cleanup (`backend/agents/script_generator.py`, `tests/test_quantity_cart_isolation.py`).

**Verified (run4):** clean + buggy false alarms **0**; bugs still **6/6**.

## Status

- `cart_total`: **closed** (run3/run4).
- Quantity false alarm: **closed** (run4).
- Gate J: strong partial evidence; 1 clean feature still imperfect (23/24) — keep explicit.
