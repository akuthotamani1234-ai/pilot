# 02 — Failure classification validation

**Status: PARTIALLY VERIFIED · score: 6/10**  
No precision/recall or false-positive rate is calculated here: the fresh test run was environment-blocked, and there is no complete, independently labeled confusion matrix in this evidence set.

## Source inspected

- Web rules: `backend/agents/failure_analysis.py` (`classify`, rule-based classifier, `failure_analysis_agent`). Rules distinguish product defects, assertion failures, locator/script errors, network/timeout, auth, third-party, flaky and inconclusive outcomes. Optional AI may suggest a category but does not directly set final severity/verdict per source comments.
- Android rules: `backend/android_reporting.py` (`classify_failure`, result/failure summaries) and `backend/android_pipeline.py` failure analysis stages.
- Verdict/counting: `backend/agents/reporter.py`, `backend/metrics.py`, `backend/accuracy.py`, `backend/qa_benchmark.py`.

## Scenario matrix

| Scenario | Expected | Actual evidence available | Status/confidence |
|---|---|---|---|
| Seeded incorrect UI/navigation/calculation | Application defect or assertion failure, with evidence and Not Ready where gates apply | `runs/advanced_android_20261108_162418_seeded/summary.json` records Not Ready, 8 passed and 5 failed; controlled fixture is described in `docs/28_APPIUM_RELIABILITY_AUDIT.md`. | Historical partial verification; medium. |
| Clean controlled app | No product defect; report may still say Ready with Risks for scope limits | `runs/advanced_android_20261108_162006_clean/summary.json` records Ready with Risks and 13 passed, 0 failed. | Historical partial verification; medium. |
| Invalid/stale/ambiguous locator | Locator/infrastructure or inconclusive, never silently a product defect; ambiguity must not be auto-selected | `logs/appium-final-regression.xml` includes passing `test_android_improvements` locator-recovery/uniqueness tests; current full run cannot be trusted due environment errors. | Historical mechanism verification; medium. |
| Test script or dependency/config failure | Test defect/infrastructure/setup category, not an application defect | Rule and Android tests exist; current suite shows pytest/Playwright `PermissionError` symptoms. The classifier’s response to these exact fresh failures was not run end-to-end. | Partial/unknown; low. |
| Browser crash or network interruption | Infrastructure error; preserve evidence and avoid blaming target | Source has network/timeout/error rules and Android disconnect handling. No fresh injected crash/network run was executed successfully. | Unverified end-to-end. |
| Delayed/dynamic/intermittent rendering | Wait within bounded policy, then flaky/inconclusive or infrastructure as evidence supports; human review where ambiguous | Local tests exist for delayed controls/busy pages and Android readiness. Fresh suite was blocked. | Partial source/test evidence; low current confidence. |
| Missing validation / unauthorized access | Defect only when an explicit expected rule is provided and observed violation is proven | QA contracts include seeded clean/defect assertions; historical web pipeline reports seeded defects. No fresh run. | Historical partial verification. |

## Metrics

| Metric requested | Result |
|---|---|
| Application-defect precision | Not calculated — current complete labeled run unavailable. |
| Application-defect recall | Not calculated — current complete labeled run unavailable. |
| Infrastructure classification accuracy | Not calculated — no completed independent labeled matrix. |
| False-positive rate | Not calculated. |
| False-negative rate | Not calculated. |

`backend/qa_benchmark.py` supports measured outcomes, but code presence is not itself accuracy evidence. The project’s docs also warn against publishing a general accuracy percentage from a small fixture set.

## Execution record

- Current full non-slow run: `deep_validation/pytest-nonslow.txt`; 406 passed, 21 failed, 324 errors; access-denied errors prevent attributing the run’s failures to the product.
- Historical regression report: `logs/appium-final-regression.xml`; 175 passed, 1 skipped (176 total), no test failures/errors.
- Historical web pipeline: `logs/appium-web-regression.xml`; 1 passed.

**Confidence:** medium that the classifier architecture and fixture tests are real; low for current measured classification quality.  
**Next action:** rerun controlled clean/seeded/infrastructure cases with working test temp and process permissions, then compute metrics only from completed labeled outcomes.
