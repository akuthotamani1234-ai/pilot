# Phase 2 results — Website discovery — 2026-11-10

## Scope

Phase 2 reviewed and verified the existing website-discovery behavior, added one sitemap parsing fix and regression, then ran the relevant discovery and project regression checks. Existing crawling controls and APIs were preserved. No later phase was started.

## Changes

1. `backend/agents/discovery.py`: decode XML entities in each sitemap `<loc>` value before interpreting nested sitemap URLs or enqueueing the URL. This fixes valid XML such as `?category=fruit&amp;sort=price` being requested with the literal `&amp;` text.
2. `tests/test_extensions.py`: added `test_sitemap_decodes_xml_escaped_query_parameters`, covering a local sitemap with an escaped query separator. The helper was expressed as a normal function to satisfy Ruff.
3. `tests/test_big_store.py`: set `PATTERN_SAMPLES=3` for the BigStore acceptance fixture. Its documented expectation is 3 fully tested examples, 10 smoke checks, and all 2,000 products counted. The fixture previously inherited the default `0` (visit every discovered route/item), so it did not exercise the sampling behavior its assertions described.

The application default was not changed: `PATTERN_SAMPLES=0` remains “visit every discovered route/item,” bounded by `MAX_PAGES`, `HARD_PAGE_CAP`, crawl time, and run time. Large deployments can opt into same-pattern sampling in configuration.

## Verification

Environment: Windows, Python 3.13.16, pytest 9.1.1. Pytest used `-B`, `-p no:cacheprovider`, and a fresh isolated Windows Temp basetemp to avoid the workspace/temp ACL issue.

| Check | Result | Evidence |
|---|---|---|
| XML sitemap regression before fix | Failed as expected: found query `category=fruit&amp;sort=price` instead of decoded `category=fruit&sort=price`. | `phase2-sitemap-red.txt` |
| XML sitemap regression after fix | Passed. | `phase2-sitemap-green.txt` |
| Final focused `tests/test_extensions.py tests/test_stay_in_section.py` | 13 passed in 72.39s; exit 0. | `phase2-discovery-focused-final.txt` |
| Serial complete non-slow suite | 752 passed, 65 deselected in 1584.42s (26m24s); exit 0. | `phase2-pytest-nonslow.txt` |
| BigStore without `PATTERN_SAMPLES` | Failed after the 60-minute run limit. It counted product pages as individual routes, stopped before completing tests, and detected 1/3 seeded bugs. This exposed that the fixture was not configured for its stated sampling acceptance case. | `phase2-bigstore.txt` |
| BigStore with `PATTERN_SAMPLES=3` | 3 passed in 201.84s (3m21s); all 2,000 products counted, 3 fully tested, 10 smoke-checked, run completed within budget, and all 3 seeded bugs caught. | `phase2-bigstore-rerun.txt` |
| Ruff on changed implementation/tests | Passed. | command: `ruff check backend/agents/discovery.py tests/test_extensions.py tests/test_big_store.py --no-cache` |

The focused files also passed together before the final helper formatting cleanup (13 tests); the final run above confirms them after cleanup.

The 287-entry Phase 0 SHA-256 manifest was rechecked. 280 entries are unchanged; the seven expected differences are `backend/agents/discovery.py`, `tests/test_extensions.py`, `tests/test_big_store.py`, `CHANGELOG.md`, `FEATURE_VERIFICATION_MATRIX.md`, `MASTER_TODO.md`, and `PROJECT_IMPLEMENTATION_STATUS.md`. No manifest entry is missing.

## Phase 2 coverage reviewed

- Same-site page discovery through links, sitemap URLs, menu/interaction exploration, and bounded queues already exists in `backend/agents/discovery.py`.
- Sitemap and index-sitemap traversal already exists; XML entity decoding was the identified defect.
- Route/page-design sampling and budget accounting already exist. BigStore confirms sample counts are reported for slug routes when the configured sampling mode is enabled.
- Scope, depth, page, interaction, crawl-time, and whole-run limits remain in force and are reported.
- The report distinguishes visited from unvisited/sampled pages and records crawl limits. It is not a guarantee that every possible app state was reachable or understood.

## Remaining limits and manual verification

- “Entire website” remains bounded by scope, crawl/page/time budgets, authentication, link visibility, and safe-action rules. Arbitrary unlinked or inaccessible states cannot be promised as tested.
- Protected actions such as checkout/payment and destructive writes remain gated; a user must define expected behavior and authorize a safe test environment before those flows can be exercised.
- The BigStore test is a controlled local fixture, not broad evidence for every live website or framework.
- The default `PATTERN_SAMPLES=0` can spend more time on large sites than sampling mode; the product default was intentionally preserved. Users can configure a positive sample count when representative same-design coverage is desired.
- Android, MCP, UI end-to-end, and external service verification are outside Phase 2.

## Phase gate

Phase 2 is complete based on the focused, full non-slow, and configured BigStore evidence above. Phase 3 (AI test generation) has not started and requires owner approval.
