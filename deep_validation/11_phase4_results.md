# Phase 4 results - Playwright/Pytest execution

**Date:** 2026-11-11  
**Status:** COMPLETE  
**Scope:** Generated-test execution isolation and regression behavior. No Phase 5 work started.

## Inspection and change

`backend/agents/executor.py` starts generated pytest in a separate process and, on Windows, applies a Job Object with memory/process limits and kill-on-close. Previously, if Job Object creation or process assignment raised an error, execution logged a warning and continued without those limits. This was a fail-open path.

The executor now attempts to stop the uncontained pytest process tree, closes a partially created Job Object when possible, and raises a clear `RuntimeError`. It does not continue generated tests without the configured Windows limits. `tests/test_executor_safety.py` covers Job Object creation failure and assignment failure.

The existing sandbox integration test asserts that a redacted trace is retained for a failing test. Normal executions disable traces and only retries capture them. The test inherited `TEST_RETRIES=0` from this machine, so that assertion failed despite correct product behavior. The test now explicitly sets its retry count to one. No trace, password-redaction, or safety assertion was removed or weakened.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Executor Job Object failure regressions | 2 passed | `phase4-executor-safety-unit.txt` |
| Real sandbox and browser recovery integration | 5 passed in 94.29s | `phase4-sandbox-focused.txt` |
| Ruff on changed implementation/tests | Passed | `ruff check backend/agents/executor.py tests/test_executor_safety.py tests/test_sandbox.py --no-cache` |
| Initial full serial non-slow suite | 755 passed, 65 deselected, 1 Android mock timeout in 10:42:06 | `phase4-pytest-nonslow.txt` |
| Final full serial non-slow suite with temporary keep-awake request | 756 passed, 65 deselected, 0 failed in 28:57 (exit 0) | `phase4-pytest-nonslow-awake-rerun.txt` |
| Isolated Android failure case | 1 passed in 18.15s | `phase4-android-failure-rerun.txt` |
| Full Android protocol file in isolation | 3 passed in 33.61s | `phase4-android-protocol-focused.txt` |
| Repeated failing Android mock case in fresh isolated roots | 3/3 passed (16.20s, 16.61s, 16.09s) | `phase4-android-repeat-stability.txt` |

The initial full-suite failure was `tests/test_android_protocol.py::test_mobile_generated_pipeline_with_real_pytest_and_mock_appium_transport[True-Not Ready]`. Its generated Android case exceeded the 120-second action budget while opening About, and the product returned `Insufficient Evidence`. The initial run remains recorded as failed. A separate complete keep-awake rerun passed; the diagnosis and final status appear below.

A first focused unit-test invocation also hit the known inaccessible default pytest temp root; rerunning with a dedicated Windows Temp `--basetemp` passed. The focused sandbox run used its own dedicated Temp root.

## Diagnosis and completion

The failed Android mock case reported a 22,642-second duration even though its runtime action budget is 120 seconds. Python 3.13 documents that `perf_counter` includes time elapsed during sleep and that, beginning in 3.13, it uses the same clock as `monotonic`. This strongly indicates that Windows suspended the machine while the first full suite was waiting; Windows sleep event logs were not collected, so suspend is not directly proven.

The complete serial non-slow suite was rerun while a temporary `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` request prevented system sleep. It completed with 756 passed, 65 deselected, and no failures in 28:57. The request was cleared in a `finally` block after pytest exited. The Android action budget and expected verdict remained unchanged.

Phase 4 is COMPLETE. The 65 tests marked `slow` were deselected by the existing non-slow regression command; this report does not claim those tests passed. Phase 5 remains NOT STARTED pending owner approval.

No existing files or features were deleted or replaced. No `.env` values, live provider, external website, GitHub service, or physical Android device were accessed.


## Follow-up on the Android suite failure

The exact failing parameterization passed in three additional fresh, isolated pytest invocations, each with its own Windows Temp basetemp. The complete Android protocol test file also passed. The final full-suite rerun, with system sleep temporarily prevented, passed 756 tests with no failures. Together, these results support system suspend as the cause of the initial timeout; this is not directly confirmed by Windows sleep event logs. No timeout, verdict, or test assertion was weakened.


## Phase 4 final verification - 2026-11-11

- `tests/test_executor_safety.py`: 2 passed.
- `tests/test_sandbox.py` plus browser-recovery case: 5 passed in 94.29 seconds.
- `tests/test_android_protocol.py`: 3 passed in isolation; the formerly timed-out parameterization passed three additional isolated runs.
- Ruff on changed source/tests: passed.
- Full serial non-slow suite with system sleep prevented temporarily: 756 passed, 65 deselected, 0 failed in 28:57.

Reference for the clock semantics: [Python 3.13 time documentation](https://docs.python.org/3.13/library/time.html#time.perf_counter).
