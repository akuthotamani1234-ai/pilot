# FINAL_CHANGELOG.md

Summary of roadmap work on `cursor/phase0-cloud-baseline-cb5b` (2026-11-12). See also root `CHANGELOG.md`.

## Documentation

- Phase 0 cloud re-baseline docs.
- `docs/31_PERFORMANCE_AND_LIMITS.md`.
- Deployment note: Windows primary; Linux offline/regression.
- Status / TODO / verification matrix updates.
- This Phase 18 final report set.

## Product / test changes

- **Android:** clearer env unreadiness; native CSS reject / WebView keep; safer APK archive checks; fixed premature `apk_path` gate that broke upload API.
- **Frontend:** clearer empty/error/loading copy; basic a11y; escaping preserved.
- **API:** explicit missing job/run errors; job `exit_code` exposed.
- **Repo-fix:** partial multi-tag findings reported as partial, not fully applied.
- **LLM/MCP:** clearer offline error messages; privacy/disabled paths preserved.
- **Security:** metadata SSRF hardening; more private run files blocked from `/runs`; upload length tests; redaction coverage.
- **Reporting:** verdict buckets + incomplete-coverage honesty; no invented accuracy %.
- **Executor/server:** Windows creationflags via `getattr` for Linux unit-testability.

## Verification

Linux non-slow: **816 passed**, 2 skipped, 65 deselected, ruff clean.
