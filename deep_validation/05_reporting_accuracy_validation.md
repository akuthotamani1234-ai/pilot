# 05 — Reporting accuracy validation

**Status: PARTIALLY VERIFIED · score: 6/10**

## Source inspected

- Web reports/counts: `backend/agents/reporter.py`, `backend/metrics.py`, `backend/registry.py`, `backend/excel.py`.
- Android reports/counts: `backend/android_reporting.py` (`classify_failure`, `user_coverage`, `control_coverage`, summary generation and HTML/JSON/XLSX output).
- Failure categories: `backend/agents/failure_analysis.py`.
- Test evidence: `tests/test_metrics.py`, `tests/test_run_always_reports.py`, `tests/test_results_layout.py`, `tests/test_android_pipeline.py`, `tests/test_android_improvements.py`, `tests/test_qa_contracts.py`.

Source includes separate outcome handling for passed, failed, error, blocked, inconclusive and skipped, plus coverage records for unvisited controls, omitted cases and incomplete runs. Android report source states that blocked controls are not passes and that discovery is bounded, not proof of complete app coverage.

## Outcome validation matrix

| Outcome requested | Source/test evidence | Fresh result |
|---|---|---|
| Passed with assertions | Metrics/reporting checks and Android JUnit outcome test exist. | Not freshly completed due pytest temp permissions. |
| Failed application assertion | Seeded controlled app run shows failed tests and Not Ready. | Historical: 8 pass / 5 fail, Not Ready. |
| Blocked | Android report excludes blocked cases from passed evidence; tests cover protected actions. | Historical unit coverage; fresh full run blocked. |
| Skipped | `test_junit_results_keep_pass_skip_and_failure_outcomes` is included in historical XML. | Historical test passes. |
| Untested/unvisited | Registry/coverage code records unvisited controls/pages and reasons. | Source-supported; no new report generated. |
| Inconclusive | Web/Android outcome logic and release gates preserve insufficient evidence. | Historical regression coverage; no fresh end-to-end report. |
| Infrastructure error | Classifiers distinguish infrastructure/locator/test failures; Android disconnect tests. | Historical tests pass; current environment temp failures prevented broad validation. |
| Partial/interrupted/discovery failure | Stop/resume/fallback report logic and Android partial coverage fields exist. | Source and historical tests; no fresh interrupt/device-loss execution. |
| Export matches execution | JSON/HTML/Excel writers and layout tests exist. | Not independently compared in a fresh generated run. |

## Fresh evidence and limitations

- Full non-slow regression: `deep_validation/pytest-nonslow.txt` — 406 passed, 21 failed, 324 errors, exit 1. Pytest temporary-directory and Playwright process permissions caused widespread setup/execution errors, making outcome consistency inconclusive.
- Historical Android regression XML: `logs/appium-final-regression.xml` — 175 passed, 1 skipped, no failures/errors; one opt-in UI test skipped.
- Historical clean/seeded reports: `runs/advanced_android_20261108_162006_clean/summary.json` and `runs/advanced_android_20261108_162418_seeded/summary.json`.
- No fresh accuracy denominator, coverage percentage, exported-file equality check, or confusion matrix was calculated.

**Confidence:** medium that explicit outcome/coverage logic exists and has historical test coverage; low that every requested outcome/export remains correct on the current checkout.  
**Next action:** rerun `test_metrics.py`, `test_run_always_reports.py`, `test_results_layout.py`, `test_android_pipeline.py`, and `test_qa_contracts.py` after pytest temp access works; compare summary/JSON/XLSX on one new controlled run.
