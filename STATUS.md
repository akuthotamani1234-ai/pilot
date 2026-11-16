# Qpilot — Project Status

Single source of truth for implementation vs verification. Prefer this file over
historical `FINAL_*` / phase checklist sprawl.

**Last updated:** 2026-11-16

## Shared MCP settings and Qpilot branding

MCP setup now reuses Standard account, provider/model/key, exploration and approved-flow controls. Studio keeps
private prepared configurations in memory for 15 minutes; the assistant receives an opaque reference and starts
the exact reviewed settings through `start_prepared_test`. Android startup prepares installed local Appium and
the selected emulator. Preparing, connecting and refreshing do not start automation. Current privacy and explicit
permission remain required; editing settings revokes the reference and successful repeat starts return the same job.

Public labels, generated report/launcher/package names, GitHub fix-branch and Jira labels, and current examples use
Qpilot. Legacy clients/contracts and installed-tool paths remain compatible. Demo source labels are updated for
future builds; existing APK binaries and recorded run evidence retain their original identity.

Validation: the current offline suite is **1,107 passed, 6 skipped** on Linux (16 Nov 2026, 7m 30s). An earlier Windows run passed **1,015** tests. **76 final affected checks passed**, including
desktop/mobile MCP settings and generated integration names. Ruff and changed JavaScript syntax checks passed.
The 14 November documentation review found zero broken local file links. Browser fixtures
cover shared configuration, private-input omission, invalidation and responsive layouts. These checks do not claim
a fresh arbitrary-APK run, physical-device Inspector attachment or paid-provider/third-party-host acceptance.
See [MCP setup](docs/34_MCP_SHARED_CONFIGURATION.md) for current connection and privacy behavior.

## Android coverage workspace

Implemented full discovered-scenario mode, screen-scoped control coverage, durable masked Android action events,
pending-only continuation, reviewed AI drafts, attached read-only API/SQLite checks, and known-truth case selection.
See [operation and limits](docs/33_ANDROID_COVERAGE_WORKSPACE.md).

Validation: ruff passed; 119 affected offline regressions passed; 39 MCP integration checks passed; 18 continuation,
workspace and mock Appium protocol checks passed. The browser checks cover desktop/mobile flow configuration,
coverage filtering, AI review and backend-check attachment. PR CI runs the full offline suite before merge.
Merged zero-limit/Thorough follow-up: 51 checks passed, including protected-action rules; 10 coverage-policy checks
passed, including zero as unlimited pages and positive caps with explicit reasons.

These checks do not establish exhaustive coverage of arbitrary APKs. A full physical-device/APK acceptance run and
an actual Inspector attachment are separate verification; real app defects and blocked scenarios remain visible.

## Product readiness

| Area | Status | Notes |
| --- | --- | --- |
| Web Playwright pipeline | Implemented | Offline non-slow suite green; **Thorough** raises per-run budgets only when explicit (finite; not every component) |
| Android Appium pipeline | Implemented | Offline + live emulator demos recorded |
| Studio UI | Implemented | Characterization tests; Windows `ui.bat` primary; MCP Android settings parity + incomplete-run delete |
| Optional LLM providers | Implemented | Rules-only (`LLM_PROVIDER=none`) fails closed with clear error |
| Optional MCP bridge | Implemented | Install `requirements-mcp.txt`; offline suite green; **12 tools** register via `build_server()`; `BridgeError` → `ToolError` so clients see actionable text |
| Release gates / reports | Implemented | Counts from run files only |
| Web apply-fixes (GitHub) | Implemented | Prepare scans repo; UI shows scan summary + next-steps checklist |

## Verification

| Evidence | Result |
| --- | --- |
| Offline pytest `-n 3 -m "not slow"` (Linux, 2026-11-16) | **1,107 passed**, 6 skipped, 7m 30s |
| Offline pytest `-m "not slow"` (Windows, 2026-11-14) | **1,015 passed**; earlier shared MCP/branding checkpoint |
| Earlier offline checkpoint (Linux) | **816 passed**, 2 skipped, 65 slow deselected; historical |
| Ruff | Clean |
| MCP + LLM + privacy offline | **60 passed** (`test_mcp_integration`, `test_llm_provider_errors`, `test_privacy_workflow`) |
| `LLM_PROVIDER=none` | Fails closed with explicit rules-fallback message |
| Live Android ecommerce (Sauce MDA) | Documented under `deep_validation/live_runs/` |
| Live MCP AI client (stdio → Android) | **Verified** — job done, run `android_20261112_105018_1e0c72` (see `deep_validation/live_runs/mcp_ai_assisted_test_20261112.md`) |
| Live cloud LLM / third-party IDE MCP host | Not claimed (Cursor/Claude Desktop config is local) |
| Windows Job Object / DPAPI | Production target; unit-covered |

## Setup and launch

`setup\install.bat`, also called by `ui.bat` and `run.bat`, installs Python 3.13 or 3.14, the pinned packages, Playwright Chromium, and `.env`. It does not download the Android JDK, SDK, or Appium. On a PC where those tools are already installed, **Start Android test** starts local Appium and the selected emulator. Refreshing device status only checks them.

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
