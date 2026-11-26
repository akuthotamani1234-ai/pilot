# Qpilot — Project Status

Single source of truth for implementation vs verification. Prefer this file over
historical `FINAL_*` / phase checklist sprawl.

**Last updated:** 2026-11-26

## Current state (26 Nov 2026) - read this first

The milestone entries further down are HISTORY, each dated: an entry saying "no test generation or runs from
requirements (Phase 4)" describes that day, not today. Today, on `final`:

| Area | State | Where |
|---|---|---|
| Jira / Confluence import and analysis | built; tested against a mock Jira; live run on the owner's Jira not done here (no token) | `backend/atlassian/`, `requirements_api.py` |
| Jira -> test cases -> run (Phase 4, web) | built and run live: approved ideas -> test cases -> `POST /api/requirements/executions` -> the existing engine (as "your own tests") | `atlassian/bridge.py`, `requirements_api.py:1062` |
| AI before a run | Jira executions AND Studio runs with your own tests refuse to start without a ready AI (privacy local-only + cloud `LLM_PROVIDER`, `LLM_PROVIDER=none`, Ollama not running, "no AI" chosen); never a rules fallback for them | `execution_preflight.py`, `server._has_owner_tests` |
| Outcomes and traceability per requirement | built: every case gets an outcome; `GET /api/requirements/traceability`, coverage, reports. The `TraceLink` model in `atlassian/models.py` is not what stores it (bridge tables do) | `atlassian/bridge.py` |
| Target application from Jira / Confluence (Phase 2) | built: saved project target, previous executions, Jira application custom fields, story text, Confluence pages naming the requirement; classified web / API / OpenAPI / APK / Android package / iOS bundle / repository with its engine; asks when not found; several -> choose. Mock Jira only (no live token) | `atlassian/workflow.py`, `jira.special_fields` |
| Checkout, payment sandbox, order lifecycle (Phase 5) | checkout forms on authorized sites; order placing with "Demo shop"; paying only in a declared provider sandbox (Stripe / Braintree / Adyen / Razorpay / PayPal / COD) with official test instruments; card guard against real card numbers; bounded waits for later order statuses; paying cases without a sandbox recorded Blocked. Live: BLOCKED (no sandbox application) | `payment_sandbox.py`, `templates/conftest.py` |
| Tests on pages exploring never saw | rewritten from the real page they failed on (evidence repair, up to 3 rounds); no pass without the result the case quotes | `agents/self_healing.py` |
| Web (Playwright), native Android (Appium) | built, live-verified | |
| Hybrid Android WebView (Phase 4) | built: automatic native / WebView context per step, exact WebView limitation, ChromeDriver folder / opt-in download; Jira executions run on Android through the existing engine with per-case results. Live: BLOCKED (no device / hybrid test build here) | `qa_runtime.py`, `android.py`, `requirements_api._launch_android`, `bridge._android_results` |
| Prerequisites across stories (Phase 1) | built and run live: graph from Jira links, declared preconditions, optional AI, manual; added to runs; Blocked naming the failed prerequisite; cycles reported | `atlassian/prerequisites.py`, `/api/requirements/dependencies` |
| REST API tests (Phase 3) | built and run live (Petstore): OpenAPI import, real requests, status / schema / JSON / time checks, chains, method permissions, redacted evidence; Jira test cases -> AI-planned API tests from documented operations only -> per-case results | `api_testing.py`, `requirements_api._launch_api` |
| iOS, pause-for-SSO/MFA-and-resume, per-feature inventory | NOT built | - |
| Live evidence on real enterprise apps / the owner's Jira | BLOCKED: needs the owner's Jira token, accounts, devices, payment sandbox | - |

Which code a running Studio has: `GET /api/version` and the Jira header ("build <branch> <commit>").

**Test suite health (24 Nov):** the test-order pollution and the "flaky" busy-server test are fixed (the latter was a
real discovery bug in `payment_nav.py`). Non-slow suite without `.env`: **2430 passed, 0 failed, 28 skipped** (all
skips: Postgres / Redis / MinIO / the optional `mcp` package not present here, or Windows-only).

## Requirements Intelligence (Jira Cloud + Confluence Cloud) — Phases 0–4 (web) + Milestones 1–3

**Jira workspace, guided workflow (24 Nov 2026):** renamed "Jira" in the UI, 15-item sidebar, step indicator with
Back / Next and a server-side draft, New Test, target detection (found / several / not found / unreachable with its
cause), saved targets with a protected test account, Live Execution that opens by itself and scrolls stably,
Reports per run, specific scenarios, Blocked for failed prerequisites. See docs/REQUIREMENTS_INTELLIGENCE.md
"The guided Jira workflow".

**Phase 4 (requirements → execution, websites):** accepted ideas become versioned test cases (Test Case Builder:
generate, edit, approve, stale detection); the Execution Center runs them through the existing Qpilot run
(requirement-based, hybrid or autonomous; selected / requirements / all approved / failed / impacted / regression /
epic scopes; cancel); results per case with evidence; traceability matrix with CSV export; executed coverage kept
apart from planned. One real end-to-end run (mock Jira QPL-2, local SauceDemo-like site, OpenAI): TC-QPL-2-1 Passed
with real assertions, TC-QPL-2-2 Not automated.

**Phase 5 (defects and controlled write-back):** defect records from real failures (deduplicated, triaged,
resolved / reopened, dismissible with a reason), Jira write-back proposals (results comment, Bug linked to the
story) with the exact request previewed, named-reviewer approval, idempotency markers and audit. Writes are OFF
(`QPILOT_JIRA_WRITEBACK`, workspace switch and a separate write token all required); tested against the mock only.
**Phase 8:** live SauceDemo acceptance passed (runs 5 and 6: both QPL-2 test cases Passed with real assertions, after
four fixes found by earlier live runs). **Not done:** Android requirement runs; live Jira acceptance (no read token
provided); no real Jira write has been made.

**Milestone 4 (prepared, not run live):** opt-in live read-only acceptance test for the QPL project
(`tests/test_live_jira_acceptance.py`), rehearsed against the mock. It waits for the Atlassian token to be configured
(environment Network secret, or `.env` on your own computer). **No live Jira evidence yet.**

**Milestone 3 (Studio workspace, part A):** `/requirements` with Overview, Integrations (connection cards, write-only
token, test, disconnect), Import wizard (connect → project → types & filters → preview with selection → import with
progress / cancel / retry → analyze), Requirements explorer with detail drawer (criteria and citations, analysis,
versions, links), Review center (accept / edit / reject, signed reviewer, evidence), Confluence explorer and Sync
history with audit. Phase 4–5 actions are shown as labelled "not available yet" notes. 9 browser tests against the real
server and a mock site, plus 4 API tests. **Mock only; no live Atlassian evidence.** Verified (no `.env`, 24 Nov): non-slow
suite 2424 passed, 1 failed, 32 skipped. The failure is the known timing test
(`test_busy_server_lessons`, also failing ~1 in 6 on the previous `final`; 3/3 passed when re-run alone); the extra
skips are the known test-order pollution from `test_trace_redact_link.py` (reproduced on demand; they pass when it
does not run first). Requirements tests: 265 passed three times in a row; lint clean.

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
