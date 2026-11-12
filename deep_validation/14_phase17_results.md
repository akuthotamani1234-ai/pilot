# 14 — Phase 17 Linux regression results

**Date:** 2026-11-12  
**Host:** Cursor Linux cloud, Python 3.13.18, `.venv`

## Commands

```bash
.venv/bin/python -m ruff check . --no-cache
BASE=/tmp/blowai-phase17-rerun
PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 TEMP=$BASE TMP=$BASE TMPDIR=$BASE \
  .venv/bin/python -B -m pytest -p no:cacheprovider --basetemp $BASE/pytest \
  -q --tb=line -m "not slow"
```

## Results

| Check | Result |
|---|---|
| Ruff | All checks passed |
| First full non-slow run | 6 failed, 810 passed, 2 skipped, 65 deselected |
| After regression fixes | **816 passed, 2 skipped, 65 deselected**, exit 0, 1120.76s |

## Fix commit

`142239f` — restore APK upload config flow; privacy test isolation; getattr creationflags.

## Artifacts

- `phase17-pytest-nonslow-serial.txt` (first run with 6 failures)
- `phase17-failure-repro.txt`
- `phase17-pytest-nonslow-rerun.txt` (final green)
- `phase17-ruff-rerun.txt`
