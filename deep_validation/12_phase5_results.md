# Phase 5 results - failure analysis and self-healing

**Date:** 2026-11-11  
**Status:** COMPLETE  
**Scope:** Inspect and verify website failure classification and self-healing. No Phase 6 work started.

## Read-only implementation audit

Reviewed `backend/agents/failure_analysis.py`, `backend/agents/self_healing.py`, `backend/agents/executor.py`, `backend/graph.py`, and their callers in the Android runner/pipeline. Existing behavior includes:

- Rule-based classification from error type, result outcome, evidence, and known application/network conditions. Optional vision may suggest a human-review result, while optional LLM output adds explanations/suggestions and does not replace rule-selected categories.
- Self-healing is restricted to generated-script/locator problems. It validates candidate code and rejects removed/changed assertions or newly introduced catch-all/skip paths.
- Candidate changes are backed up and rerun with related tests. A repair that passes is marked healed; a repaired script that reaches a real failing check is retained as repaired; an ineffective or breaking repair is reverted.
- Retry-on-flake preserves the original failed result and marks it flaky if it passes on retry.

No production classifier or healing logic was changed during Phase 5.

## Finding and test-fixture correction

The first run of the existing slow DemoStore healing test failed before checking any healing result because `healing_log.json` was absent. The saved learned-test helper tries the prior CSS selector, then falls back to the control's unchanged text. With DemoStore's button renamed from `#notify` to `#notify-me`, this fallback still found and clicked ?Notify me.? The seeded app bug then correctly made the expected message absent; the classifier correctly labeled that result `assertion_failure`, which is not healable. The test's expectation of a locator-repair log did not match the path it actually exercised.

Updated only `tests/test_end_to_end.py` so the saved `test_learned_5` fixture disables the name fallback for that single selector-repair scenario. Its expected-message assertion remains enabled. The rest of the learned tests retain normal fallback behavior. This makes the test produce the intended stale-selector failure instead of treating a real behavior defect as a locator problem.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Focused failure-analysis/healing regression files | 141 passed, 8 slow marked tests deselected | `phase5-failure-healing-focused.txt` |
| Ruff | Passed | `ruff check tests/test_end_to_end.py --no-cache` |
| DemoStore stale-selector repair end-to-end | 1 passed in 967.53s | `phase5-healing-e2e-fixed.txt` |

The successful run's `healing_log.json` records `#notify -> #notify-me`, method `selector-match`, status `repaired`, and a pre-repair backup at `healing/test_learned.round1.before.py`. The rerun result remains failed on the seeded missing-message assertion and is categorized `assertion_failure`; it is not reported as healed or passed. Related tests in the repaired file were rerun.

The first unmodified E2E attempt failed because the helper's fallback meant it had no locator error to repair. That diagnostic run is preserved at `phase5-healing-e2e.txt`; its assertions were not relaxed.

## Completion and limits

Phase 5 is COMPLETE based on focused classifier/healing regressions and the end-to-end repair-decision test. This does not establish behavior for every real website or a live AI provider; no external site/provider was contacted. Eight slow-marked tests were deselected from the focused batch; the dedicated slow self-healing E2E was run separately and passed. Phase 6 remains NOT STARTED pending owner approval.
