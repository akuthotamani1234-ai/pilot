# FINAL_TEST_REPORT.md

**Date:** 2026-11-12  
**Environment:** Linux cloud agent, Python 3.13.18, pytest 9.1.1, Playwright Chromium installed  
**Command basetemp:** `/tmp/blowai-phase17-rerun`

## Ruff

- ` .venv/bin/python -m ruff check . --no-cache`
- Result: **All checks passed!**
- Log: `deep_validation/phase17-ruff-rerun.txt`

## Focused QA contracts (earlier same day)

- `tests/test_qa_contracts.py`: **23 passed** in 11.62s
- Log: `deep_validation/phase1-linux-qa-contracts.txt`

## Full non-slow regression (Phase 17 final)

```text
816 passed, 2 skipped, 65 deselected in 1120.76s (0:18:40)
exit 0
```

- Marker: `-m "not slow"` (65 slow tests intentionally deselected)
- Log: `deep_validation/phase17-pytest-nonslow-rerun.txt`

## Earlier failed attempt (before regression fixes)

```text
6 failed, 810 passed, 2 skipped, 65 deselected
```

Failures fixed without weakening assertions:

1. Premature `apk_path` required check broke APK upload API — removed from `validate_mobile_config`.
2. Mobile OpenAI provider test lacked cloud-privacy fixture — test isolation fix.
3. `CREATE_NEW_PROCESS_GROUP` AttributeError on Linux when Job Object unit tests force Windows mode — `getattr` defensive fix.
4. Slack/Jira test blocked by local privacy default — test isolation fix.

Repro after fix: previously failing 6 **passed**; nearby suites 24 passed.

## Not executed here

| Area | Reason |
|---|---|
| `slow` marked tests | Intentionally deselected |
| Live Android emulator/Appium | ADB/Appium not available |
| Paid cloud LLM calls | Not authorized |
| Live GitHub PR create | Not authorized / no disposable repo |
| Live MCP client session | Deferred protocol live check |
| Live Slack/Jira network | Local fake server only in unit tests |

## Distinction

Passing offline non-slow suite ≠ proof of arbitrary-site/app production readiness. Crawl/time/action caps still bound coverage.
