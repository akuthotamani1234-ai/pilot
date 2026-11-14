# Qpilot — Project Status

Single source of truth for implementation vs verification. Prefer this file over
historical `FINAL_*` / phase checklist sprawl.

**Last updated:** 2026-11-14

## Android coverage workspace

Implemented full discovered-scenario mode, screen-scoped control coverage, durable masked Android action events,
pending-only continuation, reviewed AI drafts, attached read-only API/SQLite checks, and known-truth case selection.
See [operation and limits](docs/33_ANDROID_COVERAGE_WORKSPACE.md).

Validation: ruff passed; 119 affected offline regressions passed; 39 MCP integration checks passed; 18 continuation,
workspace and mock Appium protocol checks passed. The browser checks cover desktop/mobile flow configuration,
coverage filtering, AI review and backend-check attachment. PR CI runs the full offline suite before merge.

These checks do not establish exhaustive coverage of arbitrary APKs. A full physical-device/APK acceptance run and
an actual Inspector attachment are separate verification; real app defects and blocked scenarios remain visible.

## Product readiness

| Area | Status | Notes |
| --- | --- | --- |
| Web Playwright pipeline | Implemented | Offline non-slow suite green on Linux; **Thorough** raises per-run budgets only when explicit (finite; not every component) |
| Android Appium pipeline | Implemented | Offline + live emulator demos recorded |
| Studio UI | Implemented | Characterization tests; Windows `ui.bat` primary; MCP Android settings parity + incomplete-run delete |
| Optional LLM providers | Implemented | Rules-only (`LLM_PROVIDER=none`) fails closed with clear error |
| Optional MCP bridge | Implemented | Install `requirements-mcp.txt`; offline suite green; **11 tools** register via `build_server()`; `BridgeError` → `ToolError` so clients see actionable text |
| Release gates / reports | Implemented | Counts from run files only |
| Web apply-fixes (GitHub) | Implemented | Prepare scans repo; UI shows scan summary + next-steps checklist |

## Verification

| Evidence | Result |
| --- | --- |
| Offline pytest `-m "not slow"` (Linux) | **816 passed**, 2 skipped, 65 slow deselected |
| Ruff | Clean |
| MCP + LLM + privacy offline | **60 passed** (`test_mcp_integration`, `test_llm_provider_errors`, `test_privacy_workflow`) |
| `LLM_PROVIDER=none` | Fails closed with explicit rules-fallback message |
| Live Android ecommerce (Sauce MDA) | Documented under `deep_validation/live_runs/` |
| Live MCP AI client (stdio → Android) | **Verified** — job done, run `android_20261112_105018_1e0c72` (see `deep_validation/live_runs/mcp_ai_assisted_test_20261112.md`) |
| Live cloud LLM / third-party IDE MCP host | Not claimed (Cursor/Claude Desktop config is local) |
| Windows Job Object / DPAPI | Production target; unit-covered |

## Open by design / not claimed

- Crawl and interaction budgets bound coverage (see `docs/31_PERFORMANCE_AND_LIMITS.md`); Thorough raises floors but stays finite
- Destructive / pay / logout actions stay blocked unless explicitly allowed on staging
- Closed shadow DOM and cross-origin frames cannot be fully inventoried
- Live paid providers and third-party MCP clients require local install + user consent
- Accuracy % unpublished without a labeled live matrix
- Scripted/observed controls are not business-verified oracles

## Where to look next

- Architecture & contribution rules: `ARCHITECTURE.md`, `CONTRIBUTING.md`
- Release notes: `CHANGELOG.md`
- MCP setup: `docs/15_MCP_INTEGRATION.md`
- Android: `project-docs/12_ANDROID.md`
- Live assessments: `deep_validation/live_runs/`
