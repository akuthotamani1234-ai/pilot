# Phase 1 results - 2026-11-10

## Scope and safety

Phase 1 diagnosed pytest temporary-directory access, ran the focused QA contract tests, and attempted the non-slow regression suite. No application source, tests, configuration, APIs, or test assertions were changed. `.env` was not opened. Git was not initialized because that requires a separate decision in the roadmap.

## Environment finding

The workspace directory `deep_validation/phase1-pytest-tmp` inherited an ACL deny entry for deleting child items. Pytest could execute many tests there, but failed while enumerating/cleaning its basetemp directory. A fresh directory under the standard Windows Temp path was accessible and avoided that failure. With that temp root, Playwright could also launch during the focused contract suite.

Environment: Windows, Python 3.13.16, pytest 9.1.1. Commands used `-B`, `-p no:cacheprovider`, and `PYTHONDONTWRITEBYTECODE=1`.

Serial full-suite command, from the workspace root:

```powershell
$base = Join-Path ([System.IO.Path]::GetFullPath($env:TEMP)) 'blowai-phase1-nonslow-serial-20261110'
$env:TEMP = $base
$env:TMP = $base
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --basetemp $base -vv --tb=short -m 'not slow'
```

## Test evidence

| Run | Result | Evidence |
|---|---|---|
| `tests/test_qa_contracts.py` with a fresh standard-Temp basetemp | 23 passed in 19.63s; exit 0 | `phase1-qa-contracts-tempdir.txt` |
| Non-slow suite, quiet xdist run (`-n 3 --dist loadfile`) | Interrupted at 95% after no new output for several minutes; no pytest summary | `phase1-pytest-nonslow.txt` |
| Non-slow suite, verbose xdist run (`-n 3 --dist loadfile`) | Reached 97%; one test reported failed; run then stopped after no further output for over 20 minutes. No final pytest summary or failure traceback was produced. | `phase1-pytest-nonslow-verbose.txt` |
| Non-slow suite, serial | 751 passed, 65 deselected in 1435.06s (23m 55s); exit 0 | `phase1-pytest-nonslow-serial.txt` |
| Isolated `test_the_crawl_tests_a_page_that_shows_while_one_file_never_comes` | 1 passed in 15.16s; exit 0 | `phase1-busy-server.txt` |
| Both tests in `tests/test_busy_server_lessons.py`, serial | 2 passed in 24.85s; exit 0 | `phase1-busy-server-file.txt` |

The aggregate xdist failure was not reproduced in either isolated serial rerun or the complete serial non-slow run. It appears load-sensitive; the exact cause is unconfirmed. No test assertions were changed.

## Source integrity check

Rechecked the 287-entry Phase 0 SHA-256 manifest after testing and the completion report updates. 284 entries still match; the three changed entries are `MASTER_TODO.md`, `CHANGELOG.md`, and `PROJECT_IMPLEMENTATION_STATUS.md`, all updated to record this phase. No application source or test file differed from the Phase 0 baseline.

## Phase gate

Phase 1 test baseline is complete. The focused contract suite and the complete serial non-slow suite passed. Git metadata is absent at the project root and parent. `.gitignore` does not exclude `deep_validation/`; the evidence directory is retained in the workspace, but no Git repository was initialized and nothing was staged or committed. Git initialization remains deferred until separately approved.

## New Phase 1 artifacts

- `phase1-qa-contracts.txt`
- `phase1-qa-contracts-tempdir.txt`
- `phase1-pytest-nonslow.txt`
- `phase1-pytest-nonslow-verbose.txt`
- `phase1-pytest-nonslow-serial.txt`
- `phase1-busy-server.txt`
- `phase1-busy-server-file.txt`
- `phase1-pytest-tmp/` and the permission probe created during ACL diagnosis; retained in place.
