# FINAL_COVERAGE_REPORT.md

**Date:** 2026-11-12

## What “coverage” means in Blow AI

Blow AI reports **discovered / visited / tested / blocked / skipped / not tested / inconclusive** counts from run artifacts. It does **not** claim statement-coverage % of arbitrary customer apps.

## Product reporting improvements (Phases 12–13)

- Explicit result buckets: PASS, FAIL, BLOCKED, SKIPPED, NOT TESTED, INCONCLUSIVE (`backend/report_clarity.py`).
- Coverage-limitation text when pages/features remain unvisited due to crawl/time/action caps.
- Story/verdict wording no longer implies whole-site health from a partial crawl.
- Benchmark helper records environment and keeps `overall_accuracy_percent` null unless supported by labeled data.

## Test-suite coverage (this checkout)

| Suite | Result |
|---|---|
| Non-slow offline pytest | 816 passed, 2 skipped, 65 deselected |
| Slow / live device / paid AI | Not run |

## Limits that remain

Configured caps (`MAX_PAGES`, `HARD_PAGE_CAP`, `CRAWL_TIME_LIMIT_MIN`, Android screen/action budgets, etc.) intentionally bound exploration. See `docs/31_PERFORMANCE_AND_LIMITS.md`.
