# Requirements Intelligence: Jira Cloud + Confluence Cloud

Status: **Phase 0 complete (design, data contracts, unit tests).** Nothing talks to Atlassian yet. There is no live
Atlassian evidence. Development and automated tests use mock Atlassian servers. A real test site is configured later
for the live acceptance run.

Goal: a Jira story and its linked Confluence pages become acceptance criteria with their sources cited. The criteria
become reviewed test cases. Those run on Qpilot's existing web (Playwright) and Android (Appium) engines. The results
are kept as requirement → test → run traceability, and, with a person's approval, are reported back to Jira.

## Decisions (approved 23 Nov 2026)

1. Jira Cloud and Confluence Cloud only (`https://<site>.atlassian.net`). Data Center / Server later.
2. Mock Atlassian servers for development and automated tests. A real test site comes later, for live acceptance only.
3. The existing opt-in Jira defect creation (`backend/integrations.py`, `JIRA_*` settings, used by
   `.github/workflows/qpilot.yml`) stays exactly as it is. **Every new Jira write needs explicit approval.**
4. Reuse Qpilot's test design, review, Playwright, Appium, oracle, privacy, tenancy and audit systems. Nothing is
   duplicated, and there is no second automation engine.
5. Traceability persists across runs, with source IDs and source versions.
6. The five existing full-suite failures are baseline issues. They are recorded below and investigated separately.

## Phase 0 audit summary

| Capability | Before this work | Reused from |
|---|---|---|
| Jira defect creation (opt-in, deduplicated per site) | Implemented, verified with a local fake Jira | `integrations.py` (unchanged) |
| Jira reading (projects, JQL, paging, sync) | Missing | — |
| Confluence reading | Missing | — |
| Requirements text → instructions → plans → outcomes | Implemented, verified live (OrangeHRM PIM) | `objective.py`, `test_design.py` |
| Grounded AI (no unobserved selectors, no invented records) | Implemented, verified | `ai_grounding.py` |
| Expected results tied to an approved source | Implemented, unit-tested (`requirement_id` was the test-case ID) | `oracle.py`, `oracle_bind.py` |
| Human review of expected results / approvals queue | Implemented for observed values and heals | `review.py`, `approvals.py`, `human_review.py` |
| "Not automated" with its reason | Implemented, verified | `my_tests.py`, `objective.py` |
| Web and Android execution, evidence, reports | Implemented, verified | `graph.py`, `android_graph.py`, `android_interact.py` |
| Per-run traceability | Partial: one run only, no external IDs | `objective.outcomes()` |
| Tenants, RBAC, audit log | Offline SQLite helpers, not used by integrations | `tenancy_store.py`, `rbac.py`, `audit_store.py` |
| Secrets and privacy | Env-only Jira token, redaction, local/cloud AI policy | `safety.py`, `privacy.py` |
| Studio workspace for requirements | Missing | `frontend/` (vanilla JS) |

## Architecture

```
 Jira Cloud ──┐                                     ┌──────────── existing Qpilot ─────────────┐
 (read-only)  │  backend/atlassian/                 │                                           │
              ├─▶ client.py ─▶ jira.py ──┐          │  objective.py   instructions + plans      │
 Confluence ──┘   (auth, retry, 429,      │          │  review.py      human review gate         │
 Cloud            paging, 401=expired)    ▼          │  oracle.py      expected result ← source  │
                  confluence.py ─▶ normalize ─▶ store.py ─▶ analysis ─▶ test_design ─▶ scripts   │
                                   (models.py)   (SQLite,   (rules first,  │           │          │
                                                 tenant_id  AI only when   ▼           ▼          │
                                                 per row)   privacy allows) Playwright  Appium     │
                                                    ▲                       │           │          │
                                                    │                       └─ results + evidence ─┤
                                                    └──── trace links ◀───── objective.outcomes() ─┘
                                                    │
                                 writeback.py ─▶ approvals.py (kind jira_write) ─▶ person ─▶ Jira
                                                    └──▶ audit_store.record_audit (every read sync and write)
```

Package layout (Phase 0 creates only `models.py`):

| File | Phase | Role |
|---|---|---|
| `backend/atlassian/models.py` | 0 | Data contracts and the rules below (Pydantic v2) |
| `backend/atlassian/client.py` | 1 | One HTTP client: Basic auth (email + API token from a secret *name*), retries with backoff, `Retry-After` on 429/503, 401 → "token expired or revoked", every message redacted |
| `backend/atlassian/jira.py` | 1 | Projects, fields (finds the acceptance-criteria custom field), `POST /rest/api/3/search/jql` with `nextPageToken`, issue links, remote links; ADF → text |
| `backend/atlassian/confluence.py` | 2 | v2 pages API with `version.number`, body in storage format → sections, attachments list, linked pages from the story's remote links / page links |
| `backend/atlassian/store.py` | 1–5 | SQLite (same pattern as `approvals.py`): connections, sources + versions, requirements, criteria, conflicts, sync cursors, trace links, outbound writes |
| `backend/atlassian/analysis.py` | 3 | Acceptance-criteria extraction (rules), conflict detection, AI proposals routed to review |
| `backend/atlassian/bridge.py` | 4 | Accepted criteria → `QA_REQUIREMENTS` / my-test instructions with `requirement_id`, `oracle.bind_assertion(source="requirement")` |
| `backend/atlassian/writeback.py` | 5 | Story comments, remote links to reports, bug ↔ story links: only after approval, idempotent |
| `frontend/requirements.js` | 6 | Studio workspace (connections, story explorer, review, runs, traceability) |

## Data contracts (`backend/atlassian/models.py`)

| Model | Holds | Rules enforced |
|---|---|---|
| `Connection` | One Cloud site for one tenant | `https://<site>.atlassian.net` only; `token_ref` is the **name** of a secret, a token-shaped value is refused; `read_only=True` and `allow_writes=False` by default; unknown fields refused |
| `SourceRef` | Issue / page / attachment at one version | Real issue key or numeric page id; https link on the same Cloud domain; sha256 `content_hash`; version ≥ 1 |
| `Citation` | A quote from one source version | Source, locator (field or heading), non-empty quote |
| `AcceptanceCriterion` | `PROJ-12#AC-n` | At least one citation. Criteria taken by rules must have their text, Given/When/Then and expected outcome **inside the quote**. An AI proposal starts as `needs_review`, can't add an expected outcome that isn't quoted, and is accepted only by a named reviewer. An unautomatable criterion carries its reason |
| `Requirement` | Story/spec with sources and criteria | One tenant across all sources; criteria belong to it, no duplicates, and only cite the requirement's own sources |
| `Conflict` | Two sources disagree | Cites two different places; only a named person resolves it |
| `TraceLink` | requirement → criterion → test case → run | `passed`/`failed`/`flaky` need a run id **and** evidence; `not_automated`/`blocked`/`skipped`/`inconclusive` need a reason; evidence paths stay inside the run folder; keeps the source version the test was designed from (`is_stale()`) |
| `SyncCursor` | Resumable incremental sync | High-water `updated` time, `nextPageToken`, failed items; a token-shaped value in the error is redacted |
| `OutboundWrite` | One proposed new Jira write | `idempotency_key()` over tenant + operation + target + payload; approved/sent/failed need an approval id and a named approver; sent records Jira's answer; no credential in the payload |
| `ai_use_allowed()` | May requirement text go to an AI? | Local model: yes. Cloud: only in cloud mode with consent; confidential only when the connection allows it |

## Security contract

1. **Read-only by default.** Phase 1–3 code calls only `GET` and Jira's read-only `POST /search/jql`. Write
   methods live only in `writeback.py`, which refuses to send anything without an approved `OutboundWrite`.
2. **Approval for every new write.** Writes become rows in `approvals.py` (a new kind, `jira_write`, added in Phase
   5) and are sent only after a named person accepts. No answer means nothing is sent. The existing opt-in
   defect creation is unchanged.
3. **Secrets.** Tokens come from the environment or the cloud environment's secret store, by name
   (`token_ref`). They are never saved in SQLite, JSON, logs, reports, prompts or the browser. `safety.redact`
   gets the new names (`CONFLUENCE_API_TOKEN`).
4. **Privacy before AI.** Requirement text goes to an AI only when `ai_use_allowed()` says so. Otherwise
   extraction is rules-only, and the run says so. Prompts include only the text that is needed, never the token,
   email or attachments.
5. **Tenant isolation.** Every row has a `tenant_id`. Every query filters by it. Studio routes check access with
   `tenancy_store.assert_run_access`/`rbac.allow`. A connection belongs to one tenant.
6. **Audit.** Each sync, review decision, approval and write is recorded with `audit_store.record_audit`
   (actor, action, allowed, tenant, detail with no secrets).
7. **No invented requirements.** Every criterion cites its source version. An AI suggestion is only a proposal.
   An unautomatable scenario is marked with its reason. A test is never "passed" without a run and evidence.
8. **Network.** Only `https://<site>.atlassian.net`. Redirects to another host are refused. Response size is
   capped. Attachments are read only by their declared type and size.

## Failure handling (Phases 1–2)

| Situation | Behavior |
|---|---|
| 429 / 503 | Wait for `Retry-After` (capped), then back off exponentially. Stop after a set number of tries; the cursor stays on the last good page |
| 401 | Stop the sync with "token expired or revoked: update the secret". No retry loop |
| 403 / 404 on one item | Recorded in `failed_items`; the rest of the sync continues; status `partial` |
| Network error mid-page | The cursor keeps the `nextPageToken` of the last stored page, so the next sync resumes there |
| Same content again | Same `content_hash`, so no new version and no new review |
| Changed content | New version; trace links to the old version become **stale**, and their criteria go back to review |
| Deleted / no longer visible | Kept with status `missing`, never silently dropped from traceability |

## Testing strategy

* **Unit:** schema rules (`tests/test_atlassian_models.py`, Phase 0), ADF/storage-format parsing, extraction,
  conflict rules.
* **Contract:** a local mock Jira and mock Confluence on `127.0.0.1`. They serve recorded response shapes of the
  public Cloud APIs, including paging, 429 with `Retry-After`, 401, partial 403, and version changes. No real tenant
  data.
* **Integration:** sync → store → review → `objective` instructions → a fixture website run → trace links →
  approved writeback to the mock Jira (and a check that it is not repeated).
* **Security:** token never in files/logs/prompts, tenant A cannot read tenant B, no write without approval,
  redirect to another host refused.
* **UI:** the existing Playwright browser fixtures for the Studio panel.
* **Live acceptance (later):** a real test Atlassian site, configured through the secure credential form. It
  proves the whole chain: story → linked page → criteria → review → run → evidence → trace → Jira comment. Until
  then, no live claim is made.

## Phase plan and acceptance criteria

| Phase | Delivers | Accepted when |
|---|---|---|
| 0 | This design, `models.py`, schema unit tests | Tests pass; no existing behavior changed ✅ |
| 1 | Jira client, project discovery, JQL paging, normalization, incremental resumable sync, store, audit | Mock-server contract tests for paging / 429 / 401 / partial failure / resume |
| 2 | Confluence pages, linked pages, attachments metadata, sections, versions | Mock tests for versions, changed content → stale, provenance |
| 3 | Criteria extraction, conflicts, AI proposals, review API | Nothing un-cited reaches a test; AI-off path works |
| 4 | Accepted criteria into the existing web + Android pipelines | A fixture run produces cases carrying `requirement_id` and real results |
| 5 | Persistent trace links, approved writeback, defect ↔ story links, idempotency | Retry sends nothing twice; no write without approval |
| 6 | Studio workspace | UI tests on desktop and phone widths |
| 7 | Full test matrix and live acceptance on a real test site | Real evidence, recorded in `STATUS.md` |

## Baseline issues (before this work, investigated separately)

The full offline suite at `4754f7f` (23 Nov 2026) gave **2241 passed, 5 failed**. These five failures existed before
Requirements Intelligence. They are not hidden, skipped or counted as passing:

| Test | Area |
|---|---|
| `tests/test_classic_shop.py::test_every_route_is_visited_and_is_its_own_page_pattern` | discovery on the classic-shop fixture |
| `tests/test_classic_shop.py::test_a_clean_shop_gives_no_false_failures` | false alarms on the classic-shop fixture |
| `tests/test_classic_shop.py::test_a_planted_bug_fails_its_own_feature_and_nothing_else` | seeded-bug attribution |
| `tests/test_end_to_end.py::test_deep_testing_behind_the_login_on_a_shop` | logged-in deep testing |
| `tests/test_end_to_end.py::test_a_repaired_script_is_run_again_and_reported_with_its_real_result` | self-healing re-run reporting |

## Later roadmap (after Phase 7, not started)

* **Jira change watcher:** a webhook or scheduled poll; a changed story re-opens review and marks tests stale.
* **Requirement gap detection:** stories with no criteria, criteria with no test, pages with no story.
* **Epic / sprint intelligence:** coverage and results per epic, sprint and release.
* **Risk-based testing:** priority from story priority, change frequency, past defects and coverage.
* **Code-change impact analysis:** commits/PRs linked to stories → the tests to re-run.
* **Continuous regression:** traced tests re-run on every deploy (`/api/hooks/run`, `qpilot.yml`).

## Limitations

* Phase 0 has no network code, so Atlassian behavior is designed, not proven.
* Cloud APIs change: the plan uses `/rest/api/3/search/jql` (the older `/search` paging is being retired) and the
  Confluence v2 pages API. Both will be checked against the live site at acceptance.
* `tenancy_store`/`rbac` are offline helpers. Hosted multi-tenant isolation is still a separate open item.
