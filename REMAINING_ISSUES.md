# REMAINING_ISSUES.md

**Date:** 2026-11-12

## Blocked / not verified on this host

1. **Live Android** — No ADB/Appium/device. Offline Android tests pass; device success not proven.
2. **Live cloud LLM** — Not authorized; rules-only / mocked error paths only.
3. **Live MCP client protocol round-trip** — Still deferred beyond offline/mocked bridge tests.
4. **Live GitHub prepare→PR** — Unit-tested with mocks only.
5. **Slow pytest marker suite** — 65 tests deselected by design in Phase 17.
6. **Dependency advisory scan** — `pip-audit`/OSV not run as a formal gate.
7. **Windows Job Object live path** — Covered by unit tests with forced Windows mode; real Windows Job Object still the production target.
8. **UI live E2E in a browser** — Characterization tests exist; manual `ui.bat`/uvicorn session not run here.
9. **Overall accuracy %** — Intentionally unpublished without labeled live matrix.

## Known product limits (by design)

- Crawl/time/action/test budgets bound coverage.
- Destructive/pay/logout actions blocked unless explicitly allowed on staging.
- Local-only UI; not a multi-user shared service.
