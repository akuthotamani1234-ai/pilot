# Requirements Intelligence: Jira Cloud + Confluence Cloud

Status: **Phases 0–3 complete against a mock Atlassian site and a stub AI (read-only Jira and Confluence
connectors, sync, story ↔ page links, requirement analysis). Phase 4 (requirement → executable test case → a real
Qpilot run → real results and traceability) is implemented for websites.** It was proven end to end once with a real
Qpilot run and a real AI (OpenAI) against a local SauceDemo-like site and a mock Jira story QPL-2 (see "Phase 4" below).
There is no live Atlassian evidence yet. Phase 5 (defects; Jira write-back with approval, preview and idempotency)
is implemented and tested against the mock only; write-back is off by default and has never written to a real
Jira. Android requirement runs are not implemented.

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

Package layout (✓ exists today; the rest is planned and does not exist yet):

| File | Phase | Role |
|---|---|---|
| ✓ `backend/atlassian/models.py` | 0 | Data contracts and the rules below (Pydantic v2) |
| ✓ `backend/atlassian/client.py` | 1 | One HTTP client: Basic auth (email + API token from a secret *name*), retries with backoff, `Retry-After` on 429/503, 401 → "token expired or revoked", every message redacted |
| ✓ `backend/atlassian/jira.py` | 1 | Projects, work-item types and counts, the account check, fields (finds the acceptance-criteria custom field), `POST /rest/api/3/search/jql` with `nextPageToken`, issue links, remote links; ADF → text |
| ✓ `backend/atlassian/confluence.py` | 2 | v2 pages API with `version.number`, body in storage format → sections, linked pages from the story's remote links / page links (attachments are **not** read yet) |
| ✓ `backend/atlassian/store.py` | 1–5 | SQLite (same pattern as `approvals.py`): connections, sources + versions, sync cursors, links, analyses (criteria, conflicts, suggestions) and their history. Trace links and outbound writes come in Phase 5 (no tables yet) |
| ✓ `backend/atlassian/analysis.py` | 3 | Acceptance-criteria extraction (rules), conflict detection, AI proposals routed to review |
| `backend/atlassian/bridge.py` (planned) | 4 | Accepted criteria → `QA_REQUIREMENTS` / my-test instructions with `requirement_id`, `oracle.bind_assertion(source="requirement")` |
| `backend/atlassian/writeback.py` (planned) | 5 | Story comments, remote links to reports, bug ↔ story links: only after approval, idempotent |
| ✓ `backend/atlassian/sync.py`, `cli.py` | 1–3, M1 | Syncs and links; the read-only command line (`python -m backend.atlassian`) |
| `frontend/requirements.js` (planned) | 6 | Studio workspace (connections, story explorer, review, runs, traceability) |

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

1. **Read-only by default.** All code today calls only `GET` and Jira's read-only `POST /search/jql` and
   `/search/approximate-count`; `client.Client` refuses any other method or path, even through its private method,
   and a test checks that no other module of the package sends HTTP. Writes will live only in `writeback.py`
   (Phase 5, **not written yet**), which must refuse to send anything without an approved `OutboundWrite`.
2. **Approval for every new write.** Writes become rows in `approvals.py` (a new kind, `jira_write`, added in Phase
   5) and are sent only after a named person accepts. No answer means nothing is sent. The existing opt-in
   defect creation is unchanged.
3. **Secrets.** Tokens come from the environment or the cloud environment's secret store, by name
   (`token_ref`). They are never saved in SQLite, JSON, logs, reports, prompts or the browser. `safety.redact`
   gets the new names (`CONFLUENCE_API_TOKEN`).
4. **Privacy before AI.** Requirement text goes to an AI only when `ai_use_allowed()` says so. Otherwise
   extraction is rules-only, and the run says so. Prompts include only the text that is needed, never the token,
   email or attachments.
5. **Tenant isolation.** Every row has a `tenant_id`. Every query filters by it. A connection belongs to one
   tenant. The requirements routes (`backend/requirements_api.py`) and the approvals API take the tenant and role
   from `dashboard_auth.authorize` / `rbac` and filter every read and write by that tenant.
6. **Audit.** Each sync, analysis, review decision and refused review is recorded with
   `audit_store.record_audit` (actor, action, allowed, tenant, detail with no secrets). Writes will be too (Phase 5).
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
| Changed content | New version (the old one is kept). A stored analysis of the old version is reported **stale** (`analysis.stale()`); re-analysis keeps decisions only for unchanged suggestions. (Trace links, Phase 5, will be marked stale the same way.) |
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
                  email="qa@example.com", token_ref="JIRA_READ_API_TOKEN")  # the token stays in the environment
db = store.connect()
store.save_connection(db, conn)
print(sync_jira(db, conn, Client(conn), tenant_id="default", project="SHOP", actor="you"))
```

The read sync uses its own secret, `JIRA_READ_API_TOKEN` (Milestone 1). `JIRA_API_TOKEN` belongs to the older defect
creation, which writes to Jira, and is refused as a `token_ref`. Another name can be given in `token_ref` if it starts
with `JIRA_`, `CONFLUENCE_` or `ATLASSIAN_` and ends with `TOKEN`, `SECRET` or `KEY` (or starts with
`QPILOT_SECRET_`); every such name is redacted and kept away from test workers. In "local only" privacy mode, Jira variables are still blanked for test workers (unchanged), and
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
                    email="<you>@<company>", token_ref="JIRA_READ_API_TOKEN")
conf_c = Connection(id="conf-main", tenant_id="default", product="confluence", site_url=site,
                    email="<you>@<company>", token_ref="CONFLUENCE_API_TOKEN")  # (the same token value may be used)
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

## Milestone 1: audit findings fixed (implemented)

| Finding | Fix | Where |
|---|---|---|
| `AC1:` lines without a heading gave 0 criteria | Labelled criteria are read without a heading: `AC1:`, `AC-2 -`, `AC 3.`, `Acceptance criterion 4:`, `Criteria 5)`, with their Given/When/Then continuation lines. A plain numbered list **without** a heading is still not taken (it is as often steps to reproduce) | `analysis._labelled`, `MARKER`, `AC_LABEL` |
| Few heading / field variants | Headings: `Acceptance Criteria`, `AcceptanceCriteria`, `Acceptance_Criteria`, `Acceptance criterion`, `AC`, `ACs`, `Definition of Done`, `DoD`, `Conditions of satisfaction`, `Success criteria`, `Business rules`, with `:` / `(AC)` / an emoji after them, and an inline `Acceptance Criteria: text`. Custom field: the same names; an exact `Acceptance Criteria` wins | `analysis.AC_HEADING`, `AC_INLINE`; `jira.acceptance_field` |
| "Notes: …" became a criterion | A label or heading of other text ends the criteria: Notes, References, Links, Attachments, Out of scope, Dependencies, Assumptions, Open questions, Technical notes, Design, Background, Description, Test data … (also inside the AC field). A later criteria heading opens them again | `analysis.STOP_LABEL`, `_until_other` |
| A sync of the wrong type silently imported 0 | A full or first sync that stores nothing returns a warning naming the project's real types with counts (e.g. `QPL has: Task (5)`) | `sync.zero_result_warning`, `jira.work_item_types`, `jira.type_counts` |
| Only `Story` was importable | `Connection.work_item_types` (default `["Story"]`; Task, User Story, custom names); `sync_jira(issue_types=…)` overrides. Jira type Task / Bug / Epic → requirement kind task / bug / epic | `models.Connection`, `sync.sync_jira`, `analysis.build_requirement` |
| One token for reading and for the defect creation that writes | Read connections use `JIRA_READ_API_TOKEN` (Confluence: `CONFLUENCE_API_TOKEN`); `JIRA_API_TOKEN` and other products' keys are refused as `token_ref`. A saved connection that still names `JIRA_API_TOKEN` asks to be saved again | `models.Connection.name_not_value` |
| Accidental writes | The client refuses every non-read method and path; a test checks no other module sends HTTP; `check` / `connect` warn when the older defect creation is configured to write (all four `JIRA_*` set) | `client._request`, `cli.legacy_write_status` |
| Queue and analysis out of step | `POST /api/approvals/{id}/decide` on a requirement suggestion goes through `analysis.review_approval`: queue row and stored analysis change together. The queue itself refuses an unnamed decision of a suggestion | `server._decide_requirement_suggestion`, `approvals.decide_approval(decided_by=…)` |
| Made-up approval records | `POST /api/approvals` refuses `requirement_suggestion` (created only by analysis). A queue row that analysis did not create for that exact suggestion cannot decide it | `approvals.INTERNAL_KINDS`, `analysis._approval_matches` |
| Reviewer name was free text | At the API the reviewer is the signed-in principal (principal / OIDC login); a body field is ignored; a shared bearer / webhook token cannot sign a review (403). With Studio login off (localhost) it is recorded as `local-user` | `dashboard_auth.reviewer_identity` |
| Custom secret names not redacted | Every `JIRA_* / CONFLUENCE_* / ATLASSIAN_*` name ending in TOKEN / SECRET / KEY, and every saved or used `token_ref`, is redacted and removed from generated-test environments; read tokens are blanked for test workers in every privacy mode | `safety.extra_secret_names`, `register_secret_names`, `privacy.apply_worker_policy` |
| No safe way to test a live site | A read-only command line; the token is never an argument; validation errors never echo the input | `cli.py`, `models.safe_error` |

### The read-only command line

Put the token in `.env` (never on the command line or in chat): `JIRA_READ_API_TOKEN=<classic API token from
id.atlassian.com → Security → API tokens>`. Leave `JIRA_PROJECT` empty unless you want the older defect creation.

```text
python -m backend.atlassian check   --site https://<site>.atlassian.net --email <you>@<company>
python -m backend.atlassian connect --id jira-main --site https://<site>.atlassian.net --email <you>@<company>
python -m backend.atlassian types   --connection jira-main --project QPL      # real types and counts
python -m backend.atlassian sync    --connection jira-main --project QPL --types Story,Task
python -m backend.atlassian show    --connection jira-main QPL-2              # fields, versions, criteria
python -m backend.atlassian analyze --connection jira-main QPL-2              # rules only, no AI
```

Global options go before the command: `--tenant` (default `local`), `--db`, `--json`. Exit code 1 on any error,
with the reason (no secret in it). Scoped API tokens (which use `api.atlassian.com`) are not supported: use a
classic token with the account email.

Tests: `tests/test_atlassian_milestone1.py` (84).

## Milestone 2: import modes and the Studio API (implemented, backend only)

### Import modes (`backend/atlassian/sync.py`)

| Mode | What it reads | Notes |
|---|---|---|
| `incremental` | Work items created or updated since the last complete sync of the same scope; the first time, everything | Unchanged items keep their version (content hash). Interrupted / cancelled syncs resume from the saved page token. The result lists `new_keys`, `changed_keys` and `affected` (analysed requirements now out of date, with the reason) |
| `full` | Every work item of the project and filters | Any work-item type (Story, Task, Bug, Epic, Subtask, custom). Items Jira no longer returns are marked **missing**, never deleted, with their history kept |
| `items` | Only the given keys or work-item links (`QPL-2`, `QPL-2, QPL-5`, `https://<site>/browse/QPL-2`, board links with `?selectedIssue=`) | One `GET /issue/{key}` each. Optional one step to `subtasks`, `parent`, `linked` items (max 50), and with a Confluence connection the pages the stories link to. **Never** touches a project cursor, never marks other items missing; an item it stores keeps its project scope. A requested item Jira no longer shows is reported inaccessible (and marked missing only if it was imported before) |
| `space` | A Confluence space | As in Phase 2 |

Filters (`models.ImportFilter`): project, types, epic (`parent = KEY`), sprint (`open`, id or name), statuses, priorities,
assignee (`me`, `unassigned`, account id), labels, created / updated date ranges, summary words, and extra JQL. Every
value is quoted; extra JQL may not contain `ORDER BY` or a project clause, must have balanced brackets and quotes (so it
cannot step out of its parentheses), and is checked by Jira's read-only `POST /rest/api/3/jql/parse` before use. A
filtered import has its own scope and cursor, so it never marks the rest of the project missing.

Preview (`sync.preview`): keys, summaries, types, statuses, priority and **new / updated / unchanged / reappeared**
against what is stored, an estimated total (Jira's approximate count), paging - and nothing is written.

Each import (`sync.run_import`) adds: criteria found per new / updated work item, which need (re-)analysis, affected
requirements, duration, and the last successful sync, and is kept in `sync_runs` (history). **Importing never runs
tests.**

### Studio API (`backend/requirements_api.py`, `/api/requirements/...`)

| Route | Role action | Purpose |
|---|---|---|
| `GET capabilities` | run.read | Which workspace actions exist today; Phase 5 write-back is `false` with the phase that brings it |
| `GET overview` | run.read | Connections, requirements, pages, missing, analysed / stale, criteria, open conflicts, issues, pending reviews, last import |
| `GET / POST connections`, `DELETE connections/{id}` | run.read / tenant.manage | Connections (no token in them). Disconnect keeps imported requirements |
| `PUT / DELETE connections/{id}/token` | tenant.manage | Write-only token; the answer says only whether one is set |
| `POST connections/{id}/test` | run.write | Account name and project / space count |
| `GET connections/{id}/projects`, `.../projects/{key}/types`, `.../spaces` | run.read | Discovery, with per-type counts |
| `POST connections/{id}/jql/validate`, `.../preview` | run.write / run.read | Jira's JQL check; import preview |
| `POST connections/{id}/imports`, `GET imports[/{job}]`, `POST imports/{job}/cancel` | run.write / run.read | Background import with progress, cancel, history. One import per connection at a time (409) |
| `GET items` | run.read | Search, filter (kind, type, status, priority, analysis state, connection, space, missing), sort, page |
| `GET items/{conn}/{key}`, `.../versions` | run.read | Description, criteria with citations, sources, linked pages / stories, stale reasons, every version |
| `POST items/{conn}/{key}/analyze`, `GET .../analysis` | run.write / run.read | Rules, or `ai: auto` when the privacy settings allow it |
| `POST items/{conn}/{key}/suggestions/{id}/review` | review.write | Accept / reject; the reviewer is the signed-in person (URL-encode the id: it contains `#`) |
| `GET coverage`, `GET audit` | run.read / audit.read | Per-criterion coverage; the requirements audit trail |

Who and which tenant always come from `dashboard_auth.authorize`, never from the request. Studio login off: the
`local` tenant, actor `local-user`. A shared bearer / webhook token works in the `local` tenant but cannot sign a review.
Atlassian failures come back as `{kind, message, hint}` with no secret (an expired token is HTTP 424, so the Studio
does not mistake it for its own login).

**Tokens.** `PUT .../token` stores the token in `runs/.requirements-credentials.json`, encrypted with Windows DPAPI
(on other systems the file is owner-only, `chmod 600`). Tokens are never returned, logged or put in the audit; values
are added to redaction. A tenant uses its own stored token; the `.env` token is used **only** by the local tenant (and
the command line), so with Studio login on no tenant can use the server owner's token.

Tests: `tests/test_requirements_api.py` (48): filters, keys and links, every import mode, preview, history, and the API
(end-to-end flow, roles, tenants, shared token, token secrecy, error answers, one import at a time, imports never start
runs).

## Milestone 3: the Studio workspace, part A (implemented)

`http://127.0.0.1:8000/requirements` (sidebar: **Requirements**). Files: `frontend/requirements.html`, `.js`, `.css`
(the Accuracy lab shell and the Studio's colours and type). Everything shown comes from `/api/requirements/*`.

| Screen | What it does |
|---|---|
| Overview | Imported requirements, pages, criteria, analysed, ideas waiting, open conflicts, out-of-date analyses, missing items; connected sites; last import; the actions that exist (Import, Analyze, Review) and the ones that do not yet, shown as labelled notes (Generate test cases, Run selected / impacted / all approved tests: Phase 4), never as buttons |
| Integrations | Jira Cloud and Confluence Cloud cards: site, account email, work-item types, write-only API token (password box, cleared once sent, never shown again), test connection, remove token, disconnect (imports kept), read-only badge, last successful import; a warning when the older defect creation is configured to write |
| Import | Connect → Project → Types & filters (real types with counts; status, priority, labels, epic, sprint, assignee, dates, summary words, extra JQL with a "Check JQL with Jira" button) → Preview (new / updated / unchanged per item, untick items, load more) → Import (progress, cancel, retry, warnings, failed / missing / inaccessible items, criteria found, out-of-date analyses) → Analyze (rules; AI only if allowed) |
| Requirements | Search, type / status / analysis filters, sortable columns, paging; key, summary, type, priority, status, criteria, linked pages, analysis state, version, last synced. A row opens the detail drawer |
| Detail drawer | Details (fields, description, AC field, criteria with their quote and citation), Analysis (criteria with coverage, missing / ambiguous / incomplete / duplicate / contradictory, Jira–Confluence conflicts with both quotes, test ideas, history), Versions (every version, its content), Linked pages / related work items |
| Review center | Ideas waiting / accepted / rejected, with the requirement words they rest on; Accept, Edit (accept with corrections: the original is kept, an outcome no longer word for word in the source becomes *inferred*), Reject. The reviewer is the signed-in person; viewers and shared tokens see no decision buttons |
| Confluence | Imported pages by space; a page's headings, requirement sections, the criteria taken from it, related Jira stories, version |
| Sync history | Every import (mode, status, counts, duration, who) and the requirements audit trail |

Security in the page: all Jira / Confluence text is inserted as text (never HTML); the Atlassian token is never stored
in the browser; with Studio login on, the page asks for the Studio access token and keeps it in memory for that tab
only. Accessibility: skip link, labelled controls, tabs with arrow keys, `aria-live` status lines, focus moved on
navigation, reduced-motion progress bar; fits a 390 px phone without sideways scrolling.

Tests: `tests/test_requirements_ui.py` (9, real server + mock site in Chromium): the whole flow from connection to
review, Jira text shown as text, targeted import by link, wrong-site link, refused token, empty states, labelled
controls and phone width, sign-in with Studio login, the Confluence explorer, and the Studio links. API additions
(`GET /reviews`, review with `edit`, `can_review` from the role) in `tests/test_requirements_api.py` (52).

## Milestone 4: live read-only Jira acceptance (prepared, NOT yet run on the real site)

`tests/test_live_jira_acceptance.py` (opt-in: `QPILOT_LIVE_JIRA=1`, marker `live`) reads the QPL project on
`https://aimaniforall1234-1795449805793.atlassian.net`: the account, the project, the **real** work-item types with
counts (every type in use is imported, nothing assumed to be a Story), a preview (nothing stored), a full import, then
for QPL-2..QPL-6 the key, type, status, summary (against the expected names), description, acceptance criteria with
their locator and quote, and version 1; a second incremental and a targeted import must create no new version and no
duplicate. Every request is recorded (method, host, path, status - never headers) and the test fails unless all were
reads (GET or a read-only search POST) to that one site. Evidence: `runs/live_jira/<time>/report.md` and
`report.json`. A site or credential that does not work is reported BLOCKED (skipped), never passed.

How to run it:
* Own computer: `JIRA_READ_API_TOKEN=<token>` in `.env` (leave `JIRA_PROJECT` empty), then
  `QPILOT_LIVE_JIRA=1 QPILOT_JIRA_EMAIL=<account email> python -m pytest -m live tests/test_live_jira_acceptance.py -s`.
* Claude cloud session: add a Network secret for the host (Basic: account email + API token) in the environment's
  settings and start a new session; the proxy adds it to requests for that site only.

Rehearsal (no real site): `QPILOT_JIRA_REHEARSAL_URL=http://127.0.0.1:<mock port>` points the same test at the local
mock; its report is titled "REHEARSAL ... NOT live evidence" and kept in `runs/live_jira_rehearsal/`. Rehearsed on
24 Nov 2026: passed. **No live run has been made yet; no live evidence exists.**

## Phase 4: requirements to execution (implemented for websites)

**Flow.** Accepted test ideas (Review Center) → `POST items/{conn}/{key}/test-cases` creates stored test cases
`TC-<KEY>-<n>` → a person approves edited cases → `POST executions` starts a normal Qpilot run (the existing
`server._launch_run`, Playwright engine, AI test design, self-healing, report) with those cases → the run's
`test_cases.json` is read back → results per test case → traceability and executed coverage.

**Test cases** (`backend/atlassian/bridge.py`, tables `req_test_cases`, `req_test_case_history`). Each carries the Jira
key / Confluence page, the acceptance criteria ids, the source version, the requirement quotes it rests on, the idea it
came from and who accepted it, preconditions, steps, expected result (quoted or "inferred"), checks and test data
needs. A content fingerprint makes generation idempotent: generating again changes nothing; a changed idea makes a new
version. Statuses: `ready`, `awaiting_approval` (edited by a person; needs a named reviewer's approval), `blocked`
(needs test data that is not given, or would delete / pay / change data), `stale` (the requirement changed, the
idea is no longer accepted, or the source disappeared). Only `ready` and approved cases run; rejected, unreviewed,
stale and blocked ideas never run, and the execution says why each one was left out.

**Run hook** (`backend/requirement_tests.py`, `backend/agents/test_design.py`). The bridge passes the cases to the run
in `QA_REQUIREMENT_TESTS` (JSON; ids checked, at most 60). They are designed exactly like a person's own plain-English
tests: the AI writes steps from what exploring really found. Without an AI, or when no working code can be written,
the case is reported **Not automated** with the reason, never Passed. Imported text is data: destructive instructions
are refused like a person's. Requirement cases are never saved into the website's own test list.

**Strategies.** `requirements`: only the selected cases (`QA_REQUIREMENTS_ONLY=1`, the built-in suite is skipped and
exploring focuses on them). `hybrid`: the selected cases first, then the normal autonomous suite; exploratory results
are counted separately. `autonomous`: a normal Qpilot run, with no requirement cases.

**Scopes.** Selected cases, named requirements, all approved, failed / blocked again, impacted (cases whose version
changed since their last result), regression (everything that ran before), an epic's stories, a Confluence page.

**Results** (tables `req_executions`, `req_results`): `Passed` only when the engine's own assertions passed; `Failed`,
`Flaky`, `Blocked`, `Not automated`, `Not run`, `Cancelled` (stopped run). Each result keeps the test case version,
the source version, the run folder, the actual result and the evidence files (screenshots, traces), linked from the UI.

**API** (`/api/requirements/...`):

| Route | Role action | Purpose |
|---|---|---|
| `POST items/{conn}/{key}/test-cases` | run.write | Generate / refresh test cases from accepted ideas (refused if the analysis is stale) |
| `GET test-cases[?requirement=&status=&q=]`, `GET test-cases/{id}` | run.read | List; one case with results and version history |
| `PUT test-cases/{id}` | run.write | Edit (new version, needs approval again) |
| `POST test-cases/{id}/approve` | review.write | Approve an edited version (a named reviewer only) |
| `POST executions` | run.write | Start: strategy, scope, target (`authorized: true` required; password and AI key are used for this run only and never stored or returned) |
| `GET executions`, `GET executions/{id}`, `POST executions/{id}/cancel` | run.read / run.write | History; live progress and results; cancel |
| `GET traceability[?q=&coverage=]` | run.read | Story → criterion → test case → run → result → evidence, one row per criterion |
| `GET coverage/execution` | run.read | Planned, executed and passed kept separate, per requirement |

**UI** (`/requirements`): Test Case Builder (generate, search, select, open, edit, approve), Execution Center
(strategy, scope, target, login, AI provider / model / key, limits, browser / video / thorough options, permission
checkbox, history, live progress, cancel, results with evidence), Live execution, Test evidence, Traceability (search,
filter by coverage, CSV export), executed coverage, the requirement drawer's Test Cases / Execution Results /
Traceability tabs, and next actions in the Review Center after an acceptance.

**Evidence (24 Nov 2026).** A real end-to-end run: mock Jira QPL-2 "User Login Functionality" → import → analysis →
two ideas accepted → TC-QPL-2-1 (valid login) and TC-QPL-2-2 (wrong password) → execution `requirements` strategy → a
real Qpilot run (Chromium, OpenAI gpt-4o-mini) on a local SauceDemo-like site. **TC-QPL-2-1 Passed** with real
assertions (logged in, URL `/inventory.html`, title "Swag Labs - Products", heading "Products" visible).
TC-QPL-2-2 was reported **Not automated** (the AI could not write working code) - not Passed. That run exposed a
mapping bug (an engine "Skipped / Not automated" case was counted as executed); it was fixed and a regression test added.

Tests: `tests/test_requirements_execution.py` (17: the engine hook through the real test-design agent with a stub
AI, generation, idempotency, staleness, rejected ideas, edits and approval, result mapping, stopped runs, tenants, API
execution with a replaced launcher, no password leak, named-reviewer approval), and
`tests/test_requirements_ui.py::test_builder_execution_results_and_traceability_in_chromium` (the Phase 4 screens in a
real browser).

**Not yet:** Android requirement runs (the target selector shows it as the next milestone); sprint and Confluence-only
scopes beyond a page's linked stories; defect intelligence; Jira write-back (off; Phase 5, every write needs approval).

## Phase 5: defects and controlled Jira write-back (implemented; writes OFF, tested only against the mock)

**Defect intelligence** (`backend/atlassian/defects.py`, table `req_defects`). Built only from stored real results.
One defect per test case and failure signature (the actual result with numbers removed): the same failure in a later
run is the same defect (occurrences, executions, latest evidence), never a duplicate. Triage comes from the engine's
own failure analysis (`failure_category`, now kept on each result): `likely_defect` (application defect, expected
result not met), `test_problem` (locator, test script, test data: fix the test), `environment` (network, timeout,
authentication, third party), `needs_triage`. Lifecycle: `open` → `resolved` (a later run of the test case passed) →
`reopened` (failed again; marked as a regression). `dismissed` needs a named person and a reason, and survives later
refreshes. Flaky, Blocked, Not automated and Not run results are never defects. Traceability rows now end with the
test case's defects (story → criterion → test case → run → result → evidence → defect → Jira issue).

**Write-back** (`backend/atlassian/writeback.py`, tables `req_writes`, `req_writeback_settings`), built on the
`OutboundWrite` contract and the approvals queue (kind `jira_write`, decided by a named person only):

| Step | What happens |
|---|---|
| Propose | `results comment`: one comment per Jira story with each test case's real result; `defect`: one Bug (project from the settings or the story's project, issue type from the settings), linked to the story, with steps, expected, actual, evidence and classification. Only open, likely or untriaged defects. Nothing is sent |
| Preview | The exact JSON that would be posted is stored with the proposal and shown in the UI |
| Approve / reject | A named, signed-in reviewer; recorded in the approvals queue and the audit. The generic `/api/approvals/{id}/decide` refuses this kind (409) |
| Send | Only when **all** hold: the server owner set `QPILOT_JIRA_WRITEBACK=1`; a workspace admin switched write-back on for the connection; a separate write token `JIRA_WRITE_API_TOKEN` is stored (the read token never writes); the write is approved. Otherwise 403 and nothing is sent |
| Idempotency | The key is the hash of tenant, operation, target and content: the same proposal twice is one proposal; a sent write is never sent again. Each write carries a marker (comment text, issue label `qpilot-<key>`); before sending, and before any retry, Jira is read for it, so a write whose answer was lost is recorded, not repeated |
| Audit | Proposal, decision, refusal, send and failure, never a token |

`client.WriteClient` is the only code that can write, and only two things: `POST /rest/api/3/issue` and
`POST /rest/api/3/issue/{key}/comment`. The read `Client` still refuses every write, even through its private
method. A write is not retried after a network error or a 5xx (it may have arrived): the next attempt checks the
marker first. Only 429 is retried.

API: `GET defects`, `GET defects/{id}`, `POST defects/{id}/dismiss` (review.write); `GET writeback` (readiness per
connection with the reasons sending is blocked, proposals), `PUT writeback/settings/{conn}` and
`PUT / DELETE writeback/token` (tenant.manage), `POST writeback/proposals` (run.write), `GET writeback/{id}`,
`POST writeback/{id}/approve | reject` (review.write), `POST writeback/{id}/send` (tenant.manage).
`GET capabilities` reports `jira_write_back: true` only when the server owner allows it.

UI: **Defects and Write-back** (defects with triage, severity, status, regression, occurrences and Jira key; propose a
bug; dismiss with a reason; write-back readiness and settings; write token; proposals with the text, the exact
request, approve / reject / send, and history). The Execution Center proposes an execution's results to Jira.

Tests: `tests/test_requirements_writeback.py` (8: one defect per failure, resolve / reopen / regression, triage,
dismissal, previews, idempotent proposals, every refusal, send once with the write token, a lost answer found by
its marker and not repeated, only two kinds of write, tenant isolation) and
`tests/test_requirements_ui.py::test_defects_and_write_back_in_chromium_never_send_while_off`.

**Not done:** no write has been made to a real Jira (none is allowed without your explicit approval; the server
switch is off). Attachments are not uploaded (evidence is referenced by file name). Results comments are not
de-duplicated across different executions with identical results (each execution is its own comment).

## Phase 8: live acceptance (SauceDemo done; live Jira waits for a read token)

**Live website, 24 Nov 2026:** the real https://www.saucedemo.com/ (public demo account `standard_user`), requirement
QPL-2 "User Login Functionality" from the mock Jira (the live Jira token was not provided), real Qpilot runs with
OpenAI `gpt-4o-mini`, strategy requirement-based. Six runs; every failure was investigated and fixed at its cause:

| Run | TC-QPL-2-1 valid login | TC-QPL-2-2 wrong password | Cause found → fix |
|---|---|---|---|
| 1 | Not automated | Not automated | AI invented a selector for the error that appears only after the steps; rejected by grounding → the requirement's quoted text is evidence, prompt rule (`c399d72`) |
| 2 | Failed | Failed | `qa_login()` called like a function (NameError) → static check (`60e6c96`) |
| 3 | Passed | Passed (weak) | the test typed the masked user name `[REDACTED]` → refused (`60088e7`) |
| 4 | Not automated | Failed | the AI guessed the account → the instruction names the `qa_login` fixture (`7825c72`) |
| 5 | **Passed** | **Passed** | - |
| 6 | **Passed** | **Passed** | - |

Runs 5 and 6 (`runs/www.saucedemo.com_20261124_152720`, `..._152831`): TC-QPL-2-1 logs in with the test account and
asserts the title "Swag Labs" and the URL `/inventory.html`; TC-QPL-2-2 types the test account's user name with a wrong
password and asserts the exact required message. No result was ever marked Passed without its assertions passing.
The AI writes the code anew each run, so a cheaper model can still vary; a stronger model is more consistent.

**Live Jira (QPL-2..QPL-6, sync, Confluence):** not run. It needs a read token for the site, which was not provided;
the opt-in test `tests/test_live_jira_acceptance.py` is ready (see Milestone 4).

## The guided Jira workflow (Jira workspace)

The page at `/requirements` is called **Jira** everywhere a person reads it (routes, API paths and identifiers are
unchanged). Its sidebar group, in order: Overview, Integrations, Import Requirements, Requirements Explorer, Analyze
Requirements, Review Center, Test Cases, Execution Center, Live Execution, Reports, Traceability Matrix, Defects,
Confluence, Sync History, Audit Trail. The group collapses (remembered per browser), scrolls on its own, and a ✓
marks a step the STORES say is complete (`backend/atlassian/workflow.state`), never "the page was visited".

**One continuous test.** A step indicator with progress, Back / Next buttons and a server-side draft
(`req_workflow_drafts`, one per person and tenant: requirement ids, test case ids, strategy, target, environment,
execution id, step - never a secret) carry the test from step to step and across reloads:
Connect → Import & Continue (the Explorer opens with what was imported selected) → Analyze Selected / Analyze All
(criteria, suggestions, missing information, conflicts, coverage gaps) → Continue to Review (accept / correct /
reject, bulk accept / reject of what is shown) → Generate Test Cases (the selected requirements' accepted ideas) →
Continue to Execution / Run Selected Tests (the selection is saved first) → Run Tests (the Live Execution view opens
by itself: real events, agents and browser frames of the run) → View Report.

**New Test** (Overview, Execution Center, the finished Live view, Reports): existing requirements, import new ones,
a different website, Android, autonomous or hybrid. It starts a fresh draft (`POST /api/requirements/workflow/new`,
audited); executions, reports, requirements and test cases are all kept. A late change for the old draft (another
tab) is refused with 409.

**Target detection** (`GET /api/requirements/targets/resolve`): candidates with their source - the project's saved
target (authorized), a website an earlier execution of these requirements used (authorized when that run started),
an address written in the requirement text (a candidate only: it must be confirmed). Jira, Confluence, GitHub /
GitLab / Bitbucket, documentation and image links are never candidates. Outcomes: found; several (choose one);
not found ("Target website not found. Please enter the website URL you want to test."); and before every run
`POST /targets/check` sends one plain GET and classifies an unusable address as invalid, dns, tls, timeout,
connection, unavailable (5xx - availability, never a test result) or not_found; nothing runs then and the selection
is kept. Nothing is tested without the "I own it / I have permission" confirmation.

**Saved target and test account** (`PUT /targets`, needs `run.write` and the authorization): the website per Jira
project and environment; the optional test account is kept in the owner-only credentials file
(`credentials.set_account`: DPAPI on Windows, chmod 600 elsewhere), never in the requirements database and never
returned. A run without typed credentials uses the saved account only for that same address; typed credentials win;
another address never receives it. Jira tokens are never sent to the application under test.

**Execution preflight and the AI (26 Nov 2026).** Requirement test cases are written as browser steps by the AI
from what the run sees on the real website, so a requirement-based or hybrid run needs one. Before anything is
created, `execution_preflight.check` resolves the AI exactly as the engine will (`privacy.select_provider`: the
choice in the Execution Center, else `LLM_PROVIDER`; local-only privacy turns a cloud AI into none), checks it is
ready (key, local model), validates the target, and opens the page once in the run's Chromium (browser available;
login form -> a test account is required). Blocking problems stop the run with a recovery action; the selection is
kept. Reproduced root cause of the reported "Not automated ... choose an AI in the chat": local-only privacy + a cloud
`LLM_PROVIDER` + no AI chosen = no AI in the run, and the execution still said Complete.

Live evidence (demo Studio, mock Jira text, real www.saucedemo.com, OpenAI gpt-4o-mini chosen in the Execution
Center after "Allow cloud AI"): QPL-2 `runs/www.saucedemo.com_20261126_060926` 4/4 passed (valid login -> URL
`/inventory.html`; wrong password -> the exact required message; two generic "security around" ideas also passed but
checked nothing new - such ideas are no longer generated); QPL-3 alone `..._20261126_062132` 3/3 passed (6 product
cards with name and price; prices ascending after "lohi"; names descending after "za"), logged in automatically
although QPL-2 was not selected; the preflight first refused it because the real page showed a login form and no
account was given. An earlier QPL-3 run with AI-added ideas (`..._061309`) had 4 test mistakes, now "Requires review"
and the duplicated / baseless AI ideas are filtered.

**Cart and checkout on real websites (26 Nov 2026).** Reported: QPL-5 (Checkout) and QPL-13 (cart badge) ended "Not
automated: Not possible: The page where this applies is missing / The badge feature is missing". Reproduced with the
same work items on www.saucedemo.com: the AI was told "Not possible" whenever exploring had not seen a page or
control - but a badge after adding an item, a filled cart and the checkout steps only appear after using the site;
criteria without Given/When started with the literal step "Open the page where this applies"; and most checkout cases
were blocked before the run ("checkout", "removing" counted as destroying data). Now:

| What | Any authorized website | "Demo shop - allow placing the order" ticked |
|---|---|---|
| add to cart, open the cart, take your item out again | tested | tested |
| Checkout button, checkout pages, their forms, the order overview | tested | tested |
| the button that places the order (Finish, Place order, Confirm order ...) | never pressed: Blocked at that step | pressed (demo order) |
| payment pages / payment providers, real card details | never | never |
| delete data, log out | never | never |

The rule is enforced in the generated tests' click guard (`templates/conftest.py` `CHECKOUT_FLOW`, only for the
owner's / Jira tests; built-in tests and the crawler keep checkout closed), told to the AI (test design and code), and
a test case that places an order is listed as not run, with the reason, unless the box is ticked. The demo option
uses the engine's existing permission (staging + `ALLOW_ACTIONS=pay` + test payments, this run only) and is refused
for autonomous / hybrid runs. A requirement-based run no longer also runs the built-in site-wide checks.

Live evidence (mock Jira text of QPL-5 / QPL-13, real www.saucedemo.com, OpenAI gpt-4o-mini): before - 4 of 8 cases
ran, QPL-13-1 passed, the 3 checkout cases were Blocked at "Checkout" (`runs/www.saucedemo.com_20261126_065656`);
after - 6 of 7 cases ran through the cart into `checkout-step-one.html` (the order-placing case was listed as not run),
and with the demo box all 7 were included (`..._070422`, `..._070714`). Several of those results were "Requires
review": on screens exploring had not seen, the AI guessed a badge name, an address or used the criterion sentence as
page text - honest test mistakes, not website failures. The instructions now forbid both; letting the AI see those
screens while it writes the test is the next step.

**Several Atlassian sites.** Integrations lists every connection and offers "Connect another Jira site". Each
site has its own token slot; a token is bound to the site it was saved for, and a connection moved to another site or
account loses its token (the page says so and asks for the new one), so a token is never sent to a site it was not
saved for.

**Specific scenarios.** Rule-based ideas name what they check with executable steps: "Verify sorting by Price (low to
high)" → open the list, locate the sort control, select the option, read the prices, compare with ascending numeric
order; listing, login and quoted-message criteria likewise. A negative idea is made only for a stated constraint
(required, only, at least / at most, must not, cannot ...), never by reversing a behaviour.

**Prerequisites.** A requirement test whose subject is not the login, failing with an authentication, test-data /
precondition or infrastructure failure, is recorded **Blocked** ("Blocked: a prerequisite failed (...)"), not Failed;
a login test failing at the login stays Failed. The engine logs in with the test account before non-login tests.

**Live QPL-3 run, attempt 1 (24 Nov 2026, `runs/www.saucedemo.com_20261124_170641` and `..._170808`):** the guided
UI worked end to end (import → analysis → review → test cases → target not found → unreachable address refused →
run → live view → report → New Test → target found from the saved project target → second run with the saved
account), but all three tests were reported **Blocked**, and that was wrong. The AI-written code opened
`https://example.com/inventory_html` (an invented address the run's browser refuses), used invented class selectors
(`.product-name`), and marked the logged-in cases `guest`. Failure analysis called it "Infrastructure", and the new
Blocked rule then hid a test defect. Root cause: SauceDemo answers `/inventory.html` with HTTP 404 and renders it
(a single-page app); test design already treats such a proven rendered page as a page (`page_testable`), but the
script writer dropped every page >= 400, so the AI was given no page at all and invented one. Fixed at the causes:
the script writer uses `page_testable` too and never asks the AI without an explored page; grounding refuses a `page.goto` to an unexplored website and
`.class` selectors seen on no page; a logged-in case written as `guest` is refused (one repair, then Not automated);
an off-site navigation is a test-script defect; and Blocked never applies to it.

**Attempt 3** (`..._171644`, `..._171846`): the AI now saw the pages; its guessed class selectors were refused
(Not automated, honestly) and one sort test read items by fixed ids (Failed, classified "test mistake"). The page
model already held the product cards (`itemLinks.selector`), but neither the AI's page data nor grounding had them:
both do now, and the prompt says to read cards in the order shown, never fixed ids, for an order check.

**Attempt 4** (`runs/www.saucedemo.com_20261124_172234`, execution EX-3addbd3e30): **3 of 3 Passed** on the real site
with real assertions - 6 product cards each with a name and a `$` price; prices read after choosing "Price (low to
high)" equal their ascending sort; names after "Name (Z to A)" equal their reverse sort. The tests ran logged in
(the discovery log shows the login evidence; the inventory page needs it). New Test → target found from the saved
project target → run without typing credentials (saved account reused) (`..._172406`, EX-d924663d2c): 2 Passed,
TC-QPL-3-1 **Failed** - that run's AI code could not parse a card ("Product name and price not found"); failure
analysis checked the screen and calls it a test mistake. Both reports are kept in Reports / history. The AI writes
the code anew on each run, so results with `gpt-4o-mini` can vary between runs.

Tests: `tests/test_jira_workflow.py` (draft, New Test, cases A-D, saved account reuse, link exclusions, Blocked,
scenarios) and `tests/test_requirements_ui.py` (the guided flow in Chromium, 15-item menu, phone width).

## Phase plan and acceptance criteria

| Phase | Delivers | Accepted when |
|---|---|---|
| 0 | This design, `models.py`, schema unit tests | Tests pass; no existing behavior changed ✅ (`f73d15d`) |
| 1 | Jira client, project discovery, JQL paging, normalization, incremental resumable sync, store, audit | Mock-server contract tests for paging / 429 / 401 / partial failure / resume ✅ (mock only) |
| 2 | Confluence pages, linked pages, attachments metadata, sections, versions | Mock tests for versions, changed content → stale, provenance ✅ (mock only) |
| 3 | Criteria extraction, conflicts, AI proposals, review API | Nothing un-cited reaches a test; AI-off path works ✅ (mock + stub AI) |
| 4 | Accepted criteria into the existing web + Android pipelines | A fixture run produces cases carrying `requirement_id` and real results ✅ web (real run, mock Jira); Android not yet |
| 5 | Persistent trace links, approved writeback, defect ↔ story links, idempotency | Retry sends nothing twice; no write without approval ✅ (mock only; writes off) |
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
* With Studio login on, the access token must be pasted again after a page reload. Suggestions are listed by `GET /api/approvals`
  and decided by `POST /api/approvals/{id}/decide` (signed-in reviewer), or by `analysis.review` in Python.
* Analyses are stored per tenant and work-item key: two Jira sites of one tenant with the same project key would
  share an analysis (not expected in practice; noted for multi-site tenants).
* Import jobs run in the Studio process: a restart stops a running import (its cursor resumes it next time).
* Jira's `parent = KEY` epic filter is used; very old company-managed projects that still need `"Epic Link"` are not
  covered by the epic filter (use the JQL filter).
* Plain numbered lists in a description without an acceptance-criteria heading or `AC` labels are not read as
  criteria; the analysis reports `missing_criteria` instead. Criteria written in other languages are not recognized.
* The zero-result warning needs Jira's approximate-count endpoint; if it is unavailable the warning says the
  types could not be read.
* Cloud APIs change: the plan uses `/rest/api/3/search/jql` (the older `/search` paging is being retired) and the
  Confluence v2 pages API. Both will be checked against the live site at acceptance.
* `tenancy_store`/`rbac` are offline helpers. Hosted multi-tenant isolation is still a separate open item.
* Requirement runs: websites only (Android: next milestone). An execution runs inside the Studio process; a Studio
  restart during a run leaves it `running` until it is opened again (its run folder is then read).
* A requirement test needs an AI to become browser steps; without one it is "Not automated". The AI's code is checked
  by the engine's own assertions only.
