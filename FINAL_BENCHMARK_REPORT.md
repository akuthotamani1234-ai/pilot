# FINAL_BENCHMARK_REPORT.md

**Date:** 2026-11-12

## Policy

No overall accuracy percentage is published from demo fixtures alone.

## What exists

- Labeled truth fixtures under `tests/truth/` and shop truth JSON files.
- Historical accuracy snapshots under `project-docs/accuracy/`.
- `backend/qa_benchmark.py` / `backend/accuracy.py` helpers that record environment and refuse invented overall %.

## What was run here

Offline unit/regression tests around honesty labels and report clarity. **No new live clean/seeded device matrix** and **no claimed overall accuracy figure**.

## To produce a real accuracy claim later

1. Run controlled clean + seeded fixtures on a declared web/Android target.
2. Record environment (OS, Python, Appium/device serial, dataset version).
3. Compute precision/recall from labeled expected results only.
4. Publish denominators and limitations with the figure.
