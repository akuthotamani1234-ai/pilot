# Blow AI — Project Status

Single source of truth for implementation vs verification. Prefer this file over
historical `FINAL_*` / phase checklist sprawl.

**Last updated:** 2026-11-12

## Product readiness

| Area | Status | Notes |
| --- | --- | --- |
| Web Playwright pipeline | Implemented | Offline non-slow suite green on Linux |
| Android Appium pipeline | Implemented | Offline + live emulator demos recorded |
| Studio UI | Implemented | Characterization tests; Windows `ui.bat` primary |
| Optional LLM providers | Implemented | Rules-only (`LLM_PROVIDER=none`) fails closed with clear error |
| Optional MCP bridge | Implemented | Install `requirements-mcp.txt`; offline suite green; **11 tools** register via `build_server()`; `BridgeError` → `ToolError` so clients see actionable text |
| Release gates / reports | Implemented | Counts from run files only |

## Verification

| Evidence | Result |
| --- | --- |
| Offline pytest `-m "not slow"` (Linux) | **816 passed**, 2 skipped, 65 slow deselected |
| Ruff | Clean |
| MCP + LLM + privacy offline | **60 passed** (`test_mcp_integration`, `test_llm_provider_errors`, `test_privacy_workflow`) |
| `LLM_PROVIDER=none` | Fails closed with explicit rules-fallback message |
| Live Android ecommerce (Sauce MDA) | Documented under `deep_validation/live_runs/` |
| Live cloud LLM / live MCP client IDE session | Not claimed on this host |
| Windows Job Object / DPAPI | Production target; unit-covered |

## Open by design / not claimed

- Crawl and interaction budgets bound coverage (see `docs/31_PERFORMANCE_AND_LIMITS.md`)
- Destructive / pay / logout actions stay blocked unless explicitly allowed on staging
- Live paid providers and third-party MCP clients require local install + user consent
- Accuracy % unpublished without a labeled live matrix

## Where to look next

- Architecture & contribution rules: `ARCHITECTURE.md`, `CONTRIBUTING.md`
- Release notes: `CHANGELOG.md`
- MCP setup: `docs/15_MCP_INTEGRATION.md`
- Android: `project-docs/12_ANDROID.md`
- Live assessments: `deep_validation/live_runs/`
