# Qpilot X — Phase 2 discovery increments

**Date:** 2026-11-18  
**Branch:** `cursor/qpilot-x-phase0-baseline-f72b`

## Measured discovery gap from Phase 1

Run4 clean: **23/24** features correct. Remaining miss:

- `orders.tracking` — detected on `/orders/{id}` but **never tested** (no matching cases)

Same root pattern as `cart_total`: default journey budget `LARGE=20` filled with short “Shop on” cases before the orders/tracking journey.

## Changes in this phase

1. **Journey priority:** emit orders (+ tracking subpages) before short Shop-on cases; leave ~4 slots for forms/nav (`backend/agents/test_design.py`).
2. **Independent coverage verifier:** `coverage_verify.verify_truth_pages()` compares discovered paths to owned truth manifests (DemoStore), with missed / blocked / unknown and coverage ratio (`backend/coverage_verify.py`).
3. **Tests:** `tests/test_coverage_truth_pages.py`, extended `tests/test_journey_budget_cart_total.py`.

## Not yet Gate A complete

Still open for full discovery gate:

- Live iframe/shadow/responsive matrix evidence beyond existing discovery helpers
- Persistent graph nodes/edges with provenance store (enterprise path)
- Re-run DemoStore accuracy to confirm `orders.tracking` now executes

## Next

Re-benchmark DemoStore (optional confirmation), then Phase 3 durable swarm leases/queue.
