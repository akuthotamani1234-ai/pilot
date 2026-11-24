# Qpilot — Project Status

Single source of truth for implementation vs verification. Prefer this file over
historical `FINAL_*` / phase checklist sprawl.

**Last updated:** 2026-11-23

## Requirements Intelligence (Jira Cloud + Confluence Cloud) — Phases 0–3 + Milestones 1–3

**Milestone 3 (Studio workspace, part A):** `/requirements` with Overview, Integrations (connection cards, write-only
token, test, disconnect), Import wizard (connect → project → types & filters → preview with selection → import with
progress / cancel / retry → analyze), Requirements explorer with detail drawer (criteria and citations, analysis,
versions, links), Review center (accept / edit / reject, signed reviewer, evidence), Confluence explorer and Sync
history with audit. Phase 4–5 actions are shown as labelled "not available yet" notes. 9 browser tests against the real
server and a mock site, plus 4 API tests. **Mock only; no live Atlassian evidence.**

**Milestone 2 (backend):** import modes - incremental (new / changed keys, affected requirements, resume, cancel),
full (any work-item type, missing kept), targeted (keys or work-item links, optional sub-tasks / parent / linked items
and linked pages, own scope that never disturbs the project's), filters (epic, sprint, status, priority, assignee,
labels, dates, summary words, Jira-validated JQL that cannot escape its project), preview (new / updated / unchanged,
estimated total, nothing stored), results and history (criteria found, needs analysis, duration, last success); and
the Studio API `/api/requirements/*` (25 routes) with login, roles, tenant isolation, write-only encrypted tokens
(`.env` only for the local tenant), background imports with cancel, explorer, versions, analysis, signed reviews,
coverage, overview and audit. 48 tests (`tests/test_requirements_api.py`), mock only. Verified (no `.env`, 24 Nov):
non-slow suite **2415 passed, 0 failed, 29 skipped** (the known test-order skip); lint clean. **No Studio screens yet
(Milestone 3); no test generation or runs from requirements (Phase 4); no live Atlassian evidence.**

**Milestone 1 (audit findings fixed):** headingless `AC1:` / `AC-1` criteria, heading and field-name variants, notes and
references never criteria; configurable work-item types (Story, Task, custom) with discovery and counts, and a warning
when an import finds nothing; a separate read token (`JIRA_READ_API_TOKEN`) so reading never enables the older defect
creation, and a client that refuses every write; requirement suggestions decided through `/api/approvals` update the
stored analysis, are signed by the logged-in reviewer (not a shared token, not a body field), stay in their tenant,
and cannot be created or forged through the API; every Atlassian secret name redacted; a read-only command line
(`python -m backend.atlassian`). 84 tests (`tests/test_atlassian_milestone1.py`) against the local mock. Verified
(no `.env`, 24 Nov): affected files 275 passed / 1 skipped; non-slow suite **2367 passed, 0 failed, 29 skipped**; lint
clean. (The 29th skip and one occasional timing failure also happen on the previous `final`: test-order effects, not
Milestone 1.) **Still no
requirements API or Studio screen (Milestones 2–3), no test generation from requirements (Phase 4), no traceability
or write-back (Phase 5), and no live Atlassian evidence.**

**Phase 3:** requirement analysis (`backend/atlassian/analysis.py`): criteria copied by rules with source, version
and quote; ambiguous / incomplete / duplicate / contradictory / missing criteria; story ↔ page conflicts with both
quotes; positive / negative / boundary / security ideas marked explicit or inferred, reviewed in the existing
approval queue (`requirement_suggestion`); AI only when the privacy settings allow it, with its ideas grounded;
per-criterion coverage; stale detection; audit and history. 22 tests (`tests/test_atlassian_analysis.py`) with mock
data and a **stub AI: no live AI or Atlassian evidence**. **Phase 2:** read-only Confluence Cloud spaces and pages (sections with heading paths, lists, tables, tasks, code;
Confluence's own version numbers; malformed and very large pages handled), linked-page walks with depth / page limits
(circular, inaccessible and deleted pages handled), and story ↔ page links from Jira remote links, descriptions and
page mentions (`backend/atlassian/confluence.py`, `sync.py`), with 24 tests against a local mock site
(`tests/test_atlassian_confluence.py`). **Mock only; no live Confluence evidence. No AI used.** **Phase 1:** a read-only Jira Cloud connector and an incremental, resumable, tenant-scoped, audited story sync
(`backend/atlassian/client.py`, `jira.py`, `store.py`, `sync.py`), with 26 tests against a local mock Jira
(`tests/test_atlassian_jira_sync.py`). **Mock only; no live Jira evidence.** **Phase 0:** design, data contracts and schema tests: `docs/REQUIREMENTS_INTELLIGENCE.md`, `backend/atlassian/models.py`,
`tests/test_atlassian_models.py` (24 passed). Nothing is wired into a test run yet; there is **no live Atlassian evidence**. The existing opt-in Jira defect creation is unchanged; every new Jira write will need
approval. Baseline: the full suite at `4754f7f` had **2241 passed, 5 failed**; all five pre-existing failures are now
fixed (root causes and fixes in the design document): `tests/test_classic_shop.py` 9 passed, `tests/test_end_to_end.py`
4 passed, the deep test 3/3 on repeat, non-slow suite 2284 passed / 28 skipped, lint clean (no `.env`, 23 Nov).

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
Connection and privacy behavior is in the Studio and `README.md`.

## Android coverage workspace

Implemented full discovered-scenario mode, screen-scoped control coverage, durable masked Android action events,
pending-only continuation, reviewed AI drafts, attached read-only API/SQLite checks, and known-truth case selection.
Operation and limits are in the Android engine and `STATUS.md`.

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
| Live Android ecommerce (Sauce MDA) | Recorded in earlier local runs; those write-ups are not part of the product |
| Live MCP AI client (stdio → Android) | **Verified** on 12 Nov 2026, run `android_20261112_105018_1e0c72` |
| Live cloud LLM / third-party IDE MCP host | Not claimed (Cursor/Claude Desktop config is local) |
| Windows Job Object / DPAPI | Production target; unit-covered |

## Setup and launch

`setup\install.bat`, also called by `ui.bat` and `run.bat`, installs Python 3.13 or 3.14, the pinned packages, Playwright Chromium, and `.env`. It does not download the Android JDK, SDK, or Appium. On a PC where those tools are already installed, **Start Android test** starts local Appium and the selected emulator. Refreshing device status only checks them.

## Open by design / not claimed

- Crawl and interaction budgets bound coverage; Thorough raises floors but stays finite
- Destructive / pay / logout actions stay blocked unless explicitly allowed on staging
- Closed shadow DOM and cross-origin frames cannot be fully inventoried
- Live paid providers and third-party MCP clients require local install + user consent
- Accuracy % unpublished without a labeled live matrix
- Scripted/observed controls are not business-verified oracles

## Where to look next

- Architecture & contribution rules: `ARCHITECTURE.md`, `CONTRIBUTING.md`
- Release notes: `CHANGELOG.md`
- Install and run: `README.md`, `DEPLOYMENT.md`
