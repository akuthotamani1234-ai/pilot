# Requirements Intelligence: Jira Cloud + Confluence Cloud

Status: **Phases 0–3 complete against a mock Atlassian site and a stub AI (read-only Jira and Confluence
connectors, sync, story ↔ page links, requirement analysis).** They are tested only against a local mock server, and
the AI part only with a stub. There is no live Atlassian or live-AI evidence. Nothing is wired into a test run yet
(Phase 4). Nothing is written to Atlassian.

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
6. The five existing full-suite failures were baseline issues, investigated separately. All five are now fixed (see below).

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

## Phase 1: the read-only Jira connector (implemented)

| File | What it does |
|---|---|
| `backend/atlassian/client.py` | `Client`: Basic auth with the connection's email and the token read from the secret named by `token_ref` at request time. Allows only GET and the read-only search POSTs (`READ_POSTS`). Retries 429/502/503/504 and network errors (`Retry-After` in seconds or as an HTTP date, capped by `max_wait`, otherwise exponential back-off). 401 → `auth_expired` with no retry. 403/404/400 are named errors. Redirects are never followed. Answers over 10 MB are refused. Error texts are redacted (the token value, `ATATT…` patterns). `base_url` accepts only a loopback mock server. |
| `backend/atlassian/jira.py` | `projects()` (paged `/project/search`), `acceptance_field()` (the custom field named "Acceptance Criteria"), `search()` (`POST /rest/api/3/search/jql` with `nextPageToken`), `build_jql()` (project key checked, strings escaped, `ORDER BY` refused in filters, `ORDER BY updated ASC, key ASC`), `adf_to_text()`, `normalize()` → `SourceRef` + plain story fields + a content hash over what a tester reads. |
| `backend/atlassian/store.py` | SQLite `runs/.requirements.sqlite` (a linked file is refused). Connections (no token), sources (newest version), `source_versions` (every version), sync cursors. Every function requires and filters by the tenant. |
| `backend/atlassian/sync.py` | `sync_jira()`: first sync reads the whole scope; later syncs read `updated >= last sync − 14 h 1 min` (JQL uses the Jira user's time zone and minutes; unchanged re-reads are recognized by hash). The cursor is saved after every page. A failure or page limit resumes from the saved page token. An expired token re-reads the same query. Unreadable stories go to `failed_items` and the high-water mark stays, so they are retried. A complete full sync marks stories Jira no longer returns as missing (kept, with history). A connection of another tenant is refused. Every sync, including a refused one, is written to `audit_store`. |

Using it (Studio screens come in Phase 6):

```python
from backend.atlassian import store
from backend.atlassian.client import Client
from backend.atlassian.models import Connection
from backend.atlassian.sync import sync_jira

conn = Connection(id="jira-main", tenant_id="default", product="jira", site_url="https://<site>.atlassian.net",
                  email="qa@example.com", token_ref="JIRA_API_TOKEN")  # the token stays in the environment
db = store.connect()
store.save_connection(db, conn)
print(sync_jira(db, conn, Client(conn), tenant_id="default", project="SHOP", actor="you"))
```

The read sync reuses the existing `JIRA_API_TOKEN` name by default. Any other secret name can be given in
`token_ref`. In "local only" privacy mode, Jira variables are still blanked for test workers (unchanged), and
`CONFLUENCE_API_TOKEN` is now blanked too and redacted like the other secrets.

Tests: `tests/test_atlassian_jira_sync.py` (26) against `tests/atlassian_mock.py`, a local mock of the Jira Cloud
v3 endpoints above. It checks Basic auth, injects faults, expires page tokens and records every request.

## Phase 2: Confluence pages and story links (implemented)

| File | What it does |
|---|---|
| `backend/atlassian/confluence.py` | `spaces()` (v2, cursor paging, key filter), `space_pages()` (a space's pages, newest change first, storage body), `get_page()`, `find_page()` (a link written as space + title). `extract()` turns storage-format XHTML into sections with their heading path. Paragraphs, list items (nested, in reading order), table rows (`cell \| cell`), tasks and code macros are kept word for word. Sections are marked `requirement_like` from their headings (rules, acceptance, requirements, scenarios…) or wording (must, shall, Given/When/Then). It also finds links to pages (by URL, by id, by space + title), to Jira issues (`/browse/KEY`, the Jira macro, keys in text) and counts links to other sites. Malformed markup is read as far as it goes (unclosed headings and paragraphs end at the next block). Large pages are capped at 400 sections × 400 blocks × 4,000 characters (`truncated: true`), and the content hash still covers all the text. `normalize()` keeps **Confluence's own version number**. |
| `backend/atlassian/sync.py` | `sync_confluence_space()`: first sync reads every page of the space. Later syncs stop at the first page older than the last complete sync. The cursor is saved after every listing page, so a sync resumes. A page that can't be read goes to `failed_items` (status `partial`, high-water not moved). A complete full sync marks pages no longer listed as missing. `follow_links()`: breadth-first from given pages up to `depth` link steps and `max_pages` pages; each page is read once, so circular links end. A page answered *not found* / *no permission* is listed as inaccessible and marked missing if it was stored. A page too large or unreadable is a failed item, not a deletion. A site-wide problem (expired token, rate limit after retries, network) stops the walk with its reason. `link_story()`: a synced story → the pages its Jira remote links (`pageId` in the global id or the URL) and its description point to, plus stored pages that mention it. Each link records how it was found. Then the walk continues to the pages those link to. |
| `backend/atlassian/store.py` | `upsert_source(..., native_version=True)` keeps Confluence's version number (an older number is refused). `links` table (`specified_by`, `links_to`, `mentions`, how each was found, first/last seen). `find_sources()`, `mark_source_missing()`. |
| `backend/atlassian/jira.py` | `remote_links()`: one more Jira read (`GET /rest/api/3/issue/{key}/remotelink`). |

Mentions of issue keys are linked only to stories already synced into the store, so text such as "UTF-8" never becomes
a link. Nothing in Phase 2 creates acceptance criteria, and nothing calls an AI. Sections are stored exactly as
written, with their page, version and heading path, so Phase 3 can quote them.

### Testing the Confluence integration

Automated, against the local mock site (no network, no real data):

```bash
.venv/bin/python -m pytest -q tests/test_atlassian_models.py tests/test_atlassian_jira_sync.py tests/test_atlassian_confluence.py
```

Against a real Atlassian Cloud test site (later, for live acceptance), from the repository folder, with the token in
the environment (never in code or chat):

```python
from backend.atlassian import store
from backend.atlassian.client import Client
from backend.atlassian.models import Connection
from backend.atlassian.sync import link_story, sync_confluence_space, sync_jira

site = "https://<your-test-site>.atlassian.net"
jira_c = Connection(id="jira-main", tenant_id="default", product="jira", site_url=site,
                    email="<you>@<company>", token_ref="JIRA_API_TOKEN")
conf_c = Connection(id="conf-main", tenant_id="default", product="confluence", site_url=site,
                    email="<you>@<company>", token_ref="JIRA_API_TOKEN")  # (one Atlassian API token covers both)
db = store.connect()
print(sync_jira(db, jira_c, Client(jira_c), tenant_id="default", project="<KEY>", actor="you"))
print(sync_confluence_space(db, conf_c, Client(conf_c), tenant_id="default", space_key="<SPACE>", actor="you"))
print(link_story(db, jira_c, Client(jira_c), conf_c, Client(conf_c), tenant_id="default",
                 issue_key="<KEY-1>", depth=1, max_pages=25, actor="you"))
print(store.links_from(db, "default", "jira-main:jira_issue:<KEY-1>"))
```

What to check there:
* every page has its real version number
* editing a page and syncing again makes version + 1 and keeps the old one (`store.history`)
* a restricted page shows as `inaccessible`
* the audit log has one row per sync or link run (`audit_store.list_audits(tenant_id="default")`)

## Phase 3: requirement analysis (implemented)

`backend/atlassian/analysis.py` analyses one stored story (with the pages linked to it) or one stored page. Rules
come first, then AI only if allowed.

| Step | How | Rules that cannot be bypassed |
|---|---|---|
| 1. Extract criteria | Copied by rules from the Jira acceptance-criteria field (or the *Acceptance criteria* part of the description), numbered / bulleted lines, Given/When/Then (one line or a multi-line `Scenario:`), and the requirement-like sections of linked pages (list items, tasks, *must/shall* sentences, table rows with their header, Gherkin code blocks) | Each criterion keeps source, **version**, locator (`customfield_10045`, `section: Login > Business rules (table)`) and the quoted words. Its text, Given/When/Then and expected outcome must be inside the quote (`AcceptanceCriterion` validator). Criteria needing a camera/scanner/fingerprint (the Android `DEVICE_ONLY` list) or a manual/visual/legal check are not automatable, with the reason |
| 2. Check | Ambiguous (vague words: fast, user-friendly, appropriate, etc.), incomplete (TBD/TODO, Given/When without Then), duplicate, contradictory within one source (numbers with the same unit, *can* vs *cannot*), and a story **without** criteria (`missing_criteria`: none are invented). Conflicts between the story and a linked page carry the quotes of both | Rules only. The AI does not decide issues. An open conflict blocks both criteria until a named person resolves it |
| 3. Suggest | Rule templates: positive (the criterion itself, **explicit**), negative (*break the rule*), boundary (n−1/n or n/n+1 from the source's number), security (password/login/session/payment…). With `ai="auto"` and the privacy settings allowing it, AI ideas too | Every idea is **explicit** (expected outcome quoted from the source) or **inferred** (says so). No idea for an ambiguous, disputed or unautomatable criterion. AI ideas naming an unknown criterion or an invented person/record (`ai_grounding.invented_record_problem`) are refused. Outcomes not in the source become *inferred*. Destructive words are flagged (`objective.destructive`). The AI never changes a criterion |
| 4. Review | Each idea becomes an item in the existing approval queue (`backend/approvals.py`, new kind `requirement_suggestion` in `human_review.WAITING`). `analysis.review()` decides it there with the reviewer's name | No answer means not accepted. Another tenant cannot decide it. Decisions survive re-analysis (fingerprint of criterion + idea) and are kept in `analysis_history` |
| 5. Coverage | Per criterion: `blocked` (not automatable, source gone, open conflict, rejected), `ambiguous`, `covered` (an approved scenario; **executed** coverage comes with Phase 5 traceability), `pending_review`, `uncovered` | Coverage never says "covered" without a person's approval |

* **Privacy:** `ai="off"` is rules only. `ai="auto"` asks `ai_use_allowed` with the existing privacy policy
  (`privacy.load_policy`, `runtime_mode`) and the AI provider. A local Ollama on this computer is allowed. A cloud
  AI needs cloud mode and consent, and confidential sources also need the connection's explicit permission.
  Otherwise the result says `ai: not_allowed` with the reason, and the rules result stands. The prompt contains
  only criterion ids and texts: no email, token or URL. An AI failure keeps the rules result (`ai: failed`).
* **Storage:** `analyses` (newest per requirement) and `analysis_history` (every analysis and review decision), per
  tenant. Each analysis records the exact source versions it read and the sources already missing.
  `analysis.stale()` says why it is out of date: a newer version, a source no longer visible, or a page linked
  afterwards.
* **Audit:** `requirements.analyze` and `requirements.review` in `audit_store` (refusals included).
* **No writes:** analysis reads only the local store and makes no Atlassian request (tested end to end on the mock
  site).

Example (from mock data: a story with 4 criteria and a linked page with conflicting rules; full output in the
Phase 3 report):

```
SHOP-12#AC-3  blocked   Passwords must have at least 8 characters.      (SHOP-12 v1 · customfield_10045)
SHOP-12#AC-5  blocked   Passwords must have at least 12 characters.     (900 v1 · section: Login > Business rules)
  conflict: SHOP-12#AC-3 and SHOP-12#AC-5 disagree: different characters: 8 vs 12 (quotes from both sources)
SHOP-12#AC-7  ambiguous The login page loads fast.                      vague word 'fast'
SHOP-12#AC-4/6 pending  Lock the account after 3 wrong tries.           duplicate (story and page)
  S-6 [boundary, inferred] Boundary attempts: try 2 and 3
```

### Testing the analysis

```bash
.venv/bin/python -m pytest -q tests/test_atlassian_analysis.py
```

On stored data (after the Phase 1–2 syncs):

```python
from backend.atlassian import analysis, store
db = store.connect()
a = analysis.analyze(db, "default", "jira-main:jira_issue:<KEY-1>", ai="off", actor="you")
print(analysis.summary(a))                       # criteria, issues, conflicts, suggestions, coverage
analysis.review(db, "default", a.requirement.id, a.suggestions[0].id, "accept", "you")
print(analysis.stale(db, "default", store.get_analysis(db, "default", a.requirement.id)))
```

## Phase plan and acceptance criteria

| Phase | Delivers | Accepted when |
|---|---|---|
| 0 | This design, `models.py`, schema unit tests | Tests pass; no existing behavior changed ✅ (`f73d15d`) |
| 1 | Jira client, project discovery, JQL paging, normalization, incremental resumable sync, store, audit | Mock-server contract tests for paging / 429 / 401 / partial failure / resume ✅ (mock only) |
| 2 | Confluence pages, linked pages, attachments metadata, sections, versions | Mock tests for versions, changed content → stale, provenance ✅ (mock only) |
| 3 | Criteria extraction, conflicts, AI proposals, review API | Nothing un-cited reaches a test; AI-off path works ✅ (mock + stub AI) |
| 4 | Accepted criteria into the existing web + Android pipelines | A fixture run produces cases carrying `requirement_id` and real results |
| 5 | Persistent trace links, approved writeback, defect ↔ story links, idempotency | Retry sends nothing twice; no write without approval |
| 6 | Studio workspace | UI tests on desktop and phone widths |
| 7 | Full test matrix and live acceptance on a real test site | Real evidence, recorded in `STATUS.md` |

## Baseline issues (before this work, now fixed)

The full offline suite at `4754f7f` (23 Nov 2026) gave **2241 passed, 5 failed**. These five failures existed before
Requirements Intelligence. They were investigated separately and fixed without weakening or removing any assertion.
Verified with no `.env` (as in CI): `tests/test_classic_shop.py` **9 passed** (18 min 47 s);
`tests/test_end_to_end.py` 4 passed; the deep test repeated 3 more times, **3 passed**; the non-slow suite **2284
passed, 28 skipped**; `ruff check .` clean.

| Test | Root cause | Fix |
|---|---|---|
| `test_classic_shop.py::test_every_route_is_visited_and_is_its_own_page_pattern` | Qpilot bug: header search boxes were removed from a form's fields, so the search page was never found | Discovery keeps them as `search_fields`; `_search_url` uses them |
| `test_classic_shop.py::test_a_clean_shop_gives_no_false_failures` | Test out of date: data tests are off by default (`DATA_TESTS=false`) and the test never enabled them. Enabling them exposed a Qpilot bug: a select took the next box's label ("Search Criteria") and was filled as a text box | Fixture enables `DATA_TESTS`; a control's nearby text never comes from another control's `<label>` |
| `test_classic_shop.py::test_a_planted_bug_fails_its_own_feature_and_nothing_else` | Qpilot bugs: search not found (above); help-iframe forms reused the page's form numbers, so `form1` named two forms and script generation crashed (`StopIteration`) | Frame forms are numbered after the page's own; buggy run uses the same data-test setting as the clean run it is compared with |
| `test_end_to_end.py::test_deep_testing_behind_the_login_on_a_shop` | Not random: passed only when the developer `.env` set `SWARM_SAMPLE=3`; without it (CI) 0 samples | The test sets `SWARM_SAMPLE=3`, `PATTERN_SAMPLES=0` itself |
| `test_end_to_end.py::test_a_repaired_script_is_run_again_and_reported_with_its_real_result` | Test hard-coded `test_learned_5`; learned-test order changed, so that number is now another case | The test finds the learned test by its control (`Notify me`, `#notify`) |

Note: the two ClassicShop agent runs take 8–10 minutes each. Running both slow files with more workers than CPUs can
push them past the fixtures' 1-hour limit (seen once with `-n 6` on 4 CPUs; setup timeouts, not test failures).

## Later roadmap (after Phase 7, not started)

* **Jira change watcher:** a webhook or scheduled poll; a changed story re-opens review and marks tests stale.
* **Requirement gap detection:** stories with no criteria, criteria with no test, pages with no story.
* **Epic / sprint intelligence:** coverage and results per epic, sprint and release.
* **Risk-based testing:** priority from story priority, change frequency, past defects and coverage.
* **Code-change impact analysis:** commits/PRs linked to stories → the tests to re-run.
* **Continuous regression:** traced tests re-run on every deploy (`/api/hooks/run`, `qpilot.yml`).

## Limitations

* The Jira connector is proven only against the local mock. The real Cloud API shapes (field names, ADF variants,
  rate limits, time-zone behavior of JQL dates) are checked at live acceptance.
* Deleted or no-longer-visible stories are detected only by a full sync (`full=True`), not by incremental syncs.
* Confluence: attachments (files on a page) are not read yet, only page text. Page comments, inline
  comments, blog posts, whiteboards and databases are not read. Macros other than code, tasks and the Jira macro
  contribute only their visible text. A page body larger than 10 MB is refused (failed item).
* Confluence incremental syncs see new and edited pages. Deleted or moved pages are seen by a full sync or when
  a linked page is read again.
* Links by title are resolved only within the same site. Links to other sites are counted, never followed.
* Analysis is English-only rules (vague words, units, Gherkin keywords). Contradictions are found for numbers with
  the same unit and for can / cannot wording. Other contradictions (different workflows, roles) are not detected.
  Conflict and duplicate detection compares words, not meaning.
* The AI path is tested with a stub only. A real model's suggestions are checked by the same rules but have not
  been evaluated live.
* Re-analysis numbers criteria in reading order, so an inserted criterion renumbers the ones after it. Review
  decisions follow content (fingerprint), not the number.
* There is no Studio screen yet (Phase 6). The approval queue rows appear wherever the queue is listed.
* Cloud APIs change: the plan uses `/rest/api/3/search/jql` (the older `/search` paging is being retired) and the
  Confluence v2 pages API. Both will be checked against the live site at acceptance.
* `tenancy_store`/`rbac` are offline helpers. Hosted multi-tenant isolation is still a separate open item.
