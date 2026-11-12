# Demoblaze visible execution - 6 November 2026

Target: https://www.demoblaze.com/ (the supplied Bing redirect points here).
Live studio: http://127.0.0.1:8000/

## Completed execution
Run: runs/www.demoblaze.com_20261106_123914
Standard Playwright workflow, explicitly selected Rules only, public pages, visible browser, recorded video.
11 pages inspected; 44 designed test cases; 8 generated script files.
93 individual checks: 83 passed, 10 failed, 0 skipped.
The ten failures were classified as locator/interaction problems in generated scripts, not confirmed website defects.
The generated report says Ready with Risks; this is not a clean pass or proof of complete functionality.
The report also records unresolved features and mobile layout findings requiring review.
Contact submission and Place Order remained protected; no account login/signup was performed.

The Excel download was verified (HTTP 200), all six sheets were parsed and opened in the UI:
Test Cases (44 rows), Test Results (93), Cost Summary (14), Coverage (100), Features (48), Summary (31).
A recorded WebM video exists in the run's videos directory.

## Earlier local AI attempt
Run: runs/www.demoblaze.com_20261106_122239
Ollama qwen2.5:3b timed out twice. The run stopped with Insufficient Evidence because fallback was not approved.
No functional tests ran in that attempt. The subsequent rules-only run was explicitly selected and labelled.

## Crawl corrections
Navigation/root controls are explored before the descendants of newly revealed widgets, preventing video-player controls from exhausting the budget ahead of categories/pagination.
Action-budget-limited exploration is now reported as partial.
Full exploration now collects links revealed by changed product lists, including pagination and filters, instead of applying the old sampled-list omission.
20 focused regressions passed across crawl priority, rendered pages/setup and nested component inventory.

The completed 93-check run predates the final pagination-link collection fix.
A separate visible targeted recheck confirmed six newly discovered product URLs (idp_=10 through idp_=15).
Those six product pages have not had a subsequent full test run. The original full-run report was retained.

## Evidence
runs/public_demoblaze_live_20261106_122222/LIVE_RESULT.json
runs/public_demoblaze_live_20261106_122222/PAGINATION_RECHECK.json
runs/public_demoblaze_live_20261106_122222/04-pagination-recheck.png
runs/public_demoblaze_live_20261106_122222/05-live-generated-excel.png
runs/public_demoblaze_live_20261106_122222/06-live-final-report.png

## Remaining work
Correct and rerun the generated tests for hidden video controls and multi-step opener chains.
Repeat the full pipeline after the final pagination-link fix to include the newly discovered product routes.
Investigate local-model latency before claiming reliable AI-assisted generation.
