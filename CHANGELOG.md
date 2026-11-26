# Changelog

All notable changes to Qpilot should be recorded here. Phase 0 added project status/planning documentation only; it did not alter application code or runtime behavior.

## 2026-11-26 - Phase 6: bot protection, CAPTCHA, SSO / MFA - recognised, paused, resumed with your session

- `backend/access_help.py`: recognises a bot-protection page (Cloudflare, Akamai, Imperva, DataDome, PerimeterX or a
  generic "checking your browser"), a CAPTCHA wall, HTTP 429 and an "access denied" 403 - never reported as a defect
  of the application, never solved, hidden from or tricked. The run pauses durably (`runs/<run>/pause.json`: what,
  where, since when, what helps) for the human-wait time (`HUMAN_WAIT_S`, default 180 s).
- An authorized person signs in / passes the check in their own browser and gives the run that session:
  `POST /api/runs/{job}/help` (a Playwright storage state or a Cookie header; only cookies of the application's own
  domain are kept, privately in the run). The run applies it, checks the page really opens, and goes on - the same
  run, its browser state, selected requirements and finished steps kept. `GET /api/runs/{job}/pause` and a banner in
  Live Execution show the pause with a form for the session.
- Headless logins that stop at a one-time code, a CAPTCHA or an SSO redirect now pause the same way (a visible
  window still lets the person complete it there); with the person's session the login is verified, not assumed.
- Nobody helped in time: that page is skipped as Blocked with the blocker and what would help; Jira test cases the
  run never reached are Blocked with that reason. Inner pages an account may not open stay "needs other permissions"
  (they do not pause the run).
- Verified with a real browser against a local site behind a bot check: refused without the session, opened with it.
  Live validation on a real protected site / SSO / MFA application: BLOCKED (none available here).

## 2026-11-26 - Phase 3: REST API tests (real requests, real checks), from Jira test cases

- `backend/api_testing.py` (api_inventory.py only records a website's calls; this EXECUTES API tests): OpenAPI 3 /
  Swagger 2 from a URL (checked like a website target) or text, JSON or YAML, `$ref` resolved; operations with
  parameters, body and documented responses; smoke tests for GETs that need no unknown input; `ApiTest`: method, path
  with `path_params`, query, headers, JSON body, the run's bearer / basic / header auth, expected statuses, checks on
  the JSON answer (eq / ne / contains / exists / not_exists / gte / lte / len_gte / len_eq / type / matches), the
  documented schema of the answer, a response-time limit, values saved for later requests (`{{name}}` chains).
- Safety: GET / HEAD / OPTIONS always; POST / PUT / PATCH only when the run allows them; DELETE only when named;
  anything else Blocked with the reason and never sent; requests never leave the API's host; evidence keeps each
  request and answer with Authorization, cookies, api keys, password / token fields and card-like numbers redacted.
- Jira executions with target type "api": the OpenAPI document, the methods allowed, a bearer token for the run (never
  stored); the AI maps each approved test case to tests built ONLY from documented operations (an invented operation
  is dropped; a case no operation covers is "Not automated" with the reason); the run is a Studio job with its own run
  folder (`api_results.json`, `test_cases.json`); each case's result goes through the usual collection: Passed, Failed
  (an API defect), Requires review (a check of a field the answer does not have: the test's mistake), Blocked.
- Live (mock Jira text, real AI gpt-4o-mini, real https://petstore3.swagger.io): 4 cases -> 3 Passed (find by status,
  a missing id answers 404, create a pet and read it back by its saved id), 1 Failed on a real finding (the shared
  sandbox returns `tags` as strings where its schema documents objects). Opt-in live test: `QPILOT_LIVE_API=1`.

## 2026-11-26 - Phase 5: payment sandbox, order lifecycle, no selected case left out

- `backend/payment_sandbox.py`: the payment providers' published TEST instruments and sandbox hosts (Stripe test
  mode, Braintree sandbox, Adyen test, Razorpay test mode, PayPal sandbox with a buyer account as a secret, cash on
  delivery). Execution Center "Payment sandbox": the provider the application's test mode uses + an explicit
  confirmation that no real money can move (requirement-based runs). The run then pays: staging + `ALLOW_ACTIONS=pay`
  + test payments + `QA_PAYMENT_SANDBOX`; the AI (test design and code) is given only that provider's official test
  details; the generated tests may press the order / pay button and open that provider's sandbox pages, while a LIVE
  provider's payment page stays protected.
- Card guard in every generated test (`templates/conftest.py`): a number that passes the card checksum (as every real
  card does) can be typed only when it is a published test number or the declared sandbox's - never real payment
  details. Deleting, transferring and password resets stay blocked even in a sandbox.
- A paying test case without a declared sandbox is listed AND recorded as Blocked, naming what it needs; every selected
  case that could not run (stale, not approved, needs a demo shop / sandbox) now has a stored outcome and counts in
  "selected".
- Order status that changes later (fulfilment, a webhook, a back office): the `_await_status` helper in AI test files
  reloads for a bounded time and reports "awaiting an external event" (inconclusive) when it does not come - never a
  pass, never a failure on a status that has not happened yet.
- Live validation BLOCKED: no application with a payment sandbox here. Needed: the application's staging URL with its
  payment provider in sandbox / test mode, a test account, and (PayPal) a sandbox buyer account.

## 2026-11-26 - Phase 4: hybrid Android - automatic contexts, WebView diagnosis, Jira test cases on Android

- `qa_runtime.AndroidContractAdapter`: a flow without context steps (what Jira / AI flows are) gets each step's
  context from its locator - CSS -> the app's own WebView, accessibility id / resource id / text / xpath -> native UI -
  switched automatically and recorded (`context_switches`); screen-title and toast checks return to native first. A
  flow that switches contexts itself keeps the strict rule. A WebView that cannot be driven is reported exactly: not
  debuggable (the test build must call `WebView.setWebContentsDebuggingEnabled(true)`), none open on this screen, or
  several open.
- Hybrid capabilities: a ChromeDriver folder (`tools/chromedriver` or `QPILOT_CHROMEDRIVER_DIR`) so Appium picks the
  driver matching the WebView's Chrome; download only with `QPILOT_CHROMEDRIVER_AUTODOWNLOAD=1` (and the Appium
  server's own permission); `ensureWebviewsHavePages`, `nativeWebScreenshot` (screenshots of the real device in a
  WebView context); non-Windows driver names.
- Jira executions on Android: target type "android" (installed app or Android Chrome, device id, package, activity,
  Appium server); preflight asks for what is missing (no website probe for an installed app); the cases are handed to
  the EXISTING Android run as the owner's tests, one line each tagged `[TC-...]`, AI required, no rules fallback; each
  case's result comes from the engine's own evidence (`android_interaction.json`: replayed journey -> Passed, failed
  twice -> Failed, not automated / session lost -> said so; no evidence -> Not run, never Passed).
- Live validation BLOCKED: no Android device / emulator and no hybrid test build in this environment. Needed: an
  Android device or emulator reachable by adb, Appium 2 with the UiAutomator2 driver, the app installed (a debuggable
  test build for WebView content), and a ChromeDriver matching the WebView's Chrome (or auto-download allowed).

## 2026-11-26 - Phase 2: the application under test found from Jira and Confluence, by kind

- Jira import also reads the custom fields whose names point to the application ("Environment", "Test URL",
  "Application", "APK", "App package", "Bundle ID", "API endpoint", "Repository" ...: `jira.special_fields`), stored
  as `app_fields` only when they have a value (stories without them keep their content hash and version).
- `workflow.targets_in_text` classifies what a value names: website, API endpoint, OpenAPI spec, Android APK,
  Android package, iOS bundle, repository - with the engine that tests it. Jira / Confluence / documentation / media
  addresses are never targets; a package / bundle id counts only with its own words ("package", "bundle id") or in an
  application field; a repository only in an application field.
- `workflow.resolve` reads, in order: the project's saved target, previous executions, the stories' application fields,
  their summary / description / acceptance criteria, and Confluence pages that name the selected requirements. Every
  candidate says where it came from; found ones are "not yet confirmed" until a person confirms permission.
- Execution Center lists each candidate's kind and engine; choosing an app / API / repository explains that Jira
  executions run in the browser today and how to test that target. No live Jira here (no token): verified against the
  mock Jira.

## 2026-11-26 - Selector recovery: an imaginary selector no longer abandons a test

- Phase 1's live run had TC-QPL-4-1 "Not automated": the AI wrote `[data-testid='shopping-cart-link']`, the page has
  `[data-test="shopping-cart-link"]`. Now, before code is refused: (1) the crawler keeps each page's real DOM
  vocabulary (`dom_tokens`: class names, ids, test ids from the HTML it saw); (2) a selector whose class / id / test id
  is in a real page's DOM is grounded even when it is not a recorded control; (3) a SIMPLE selector naming a real
  control by the wrong attribute is swapped for that control's observed selector (`ai_grounding.snap_selectors`;
  compound selectors are never swapped); (4) the retry gets the list of real controls; (5) for Jira / owner tests a
  last try reaches the page and checks what is certain; at run time evidence repair rewrites from the real page (up
  to 3 rounds). Expected results and stated values are never changed; if nothing works the exact refusal is reported.
- Evidence repair may drop a check of the old test only when that check's expected value was a guess (in neither the
  test case nor a real page).
- Live again (QPL-5 "is blocked by" QPL-4, only TC-QPL-5-1 selected): both cases now EXECUTE (was 1 Not automated);
  TC-QPL-5-1 Passed; the added TC-QPL-4-1 went inventory -> cart through 3 rewrites and ended "Requires review" (its
  code called expect() on a string - an AI coding error, reported, not passed).

## 2026-11-26 - Prerequisites between requirements: a persistent graph, added to runs automatically

- `backend/atlassian/prerequisites.py`: which test case needs which other one first, stored per workspace
  (`req_dependencies`). Sources: Jira issue links ("is blocked by", "depends on", "requires"), a case's declared
  preconditions / "Given ..." matched to a positive case of another requirement that establishes that state (generic
  word overlap - nothing website- or domain-specific), optionally the AI (batches of 30, only real case ids kept), and
  a person's own additions / removals (kept over every inferred edge). Login is left to the engine. Cycles are
  detected, reported and never followed.
- `bridge.plan`: every prerequisite of a selected case is added to the run even when its story was not selected
  (marked "prerequisite (added: needed by ...)"); the dependent test does the prerequisites' steps first itself, so
  tests keep their own browser state and stay isolated; a prerequisite that cannot run is listed, not dropped.
- `bridge.collect`: a test that did not pass while a prerequisite it needs Failed / was Blocked is Blocked, naming
  that prerequisite (its own result is kept as `own_status`); a test that passed stays Passed.
- API: `GET /api/requirements/dependencies`, `POST /api/requirements/dependencies/plan` (`use_ai`),
  `PUT /api/requirements/dependencies`; the graph is rebuilt (links / preconditions) before every execution.
  Execution Center says which prerequisites were added, which cannot run and which cycles were ignored.
- Live (mock Jira text, QPL-5 "is blocked by" QPL-4, real www.saucedemo.com): only TC-QPL-5-1 selected -> TC-QPL-4-1
  added automatically; TC-QPL-5-1 put a product in the cart itself and passed; the added TC-QPL-4-1 was "Not
  automated" (the AI wrote a selector the page does not have - refused by the grounding check).

## 2026-11-26 - Tests from Jira / your own cases are rewritten from the real page they failed on

- The AI writes a Jira / owner test before anyone has seen the pages it reaches after acting (a filled cart, a
  checkout step), so its locators and expected values there were guesses ("Requires review" results). Now the
  generated conftest records the real page when such a test fails (`live_page`: controls, short texts, headings,
  address) and self-healing rewrites that one test from it (`self_healing.evidence_repair`, prompt
  `evidence_repair.txt`). A rewrite is accepted only when it keeps as many checks, keeps every value the test case
  states, expects only values from the test case or the real page, adds no skip / try / `assert True`, opens no
  payment page and changes no other test; it then runs again and is kept (passes, or fails on a real check),
  continued (it got to a later page: rewritten again from there, up to 3 rounds) or undone for that test only.
- Code writing for these tests: a last try that checks only what is certain on a page exploring never reached; a value
  the test types into a form (a checkout's first name) is its own test data, not an "invented record".
- The cart's own "Remove" (on the cart page or next to "Add to cart" buttons) is allowed for these tests; "Remove"
  elsewhere stays protected. Prompts no longer carry website-specific examples.
- Live (mock Jira text of QPL-5 / QPL-13, www.saucedemo.com, gpt-4o-mini, demo shop ticked): passed went from 0-1 to
  4 of 7 real passes; healing_log.json of each run shows every rewrite, its evidence and its verdict.
- No pass without the requirement's result: a test whose case QUOTES its expected result ("Thank you for your
  order!") must check those words - code without the check is refused, and so is an evidence rewrite that drops it
  (one live run had passed QPL-5-5 by checking only that the Finish button was visible). Next run: QPL-5-5 finished the
  demo order and checked the message; 4 of 7 passed, 2 need review, 1 not automated (results vary per AI answer).

## 2026-11-26 - Jira checkout and cart tests run on real websites; only placing the order or paying is not done

- Reported: QPL-5 (Checkout) and QPL-13 (cart badge) ended "Not automated: Not possible: The page where this applies
  is missing / The badge feature is missing", with no browser activity. Reproduced with the same work items on
  www.saucedemo.com: (1) criteria without Given/When got the literal first step "Open the page where this applies";
  (2) the AI was told to answer "Not possible" whenever exploring had not seen a page or control - but a cart badge,
  a filled cart or the checkout steps only appear after using the site; (3) most other checkout cases were blocked
  before the run because "checkout" / "removing" counted as destroying data.
- Test design (`backend/llm/prompts/my_tests.txt`): states reached by using the website are not missing - the AI
  plans the steps that lead there; "Not possible" only when the website clearly cannot do it. The first step of a
  criterion without Given/When says to get there (log in, go through the pages and actions that lead there).
- Checkout (`backend/templates/conftest.py` CHECKOUT_FLOW, only for the owner's / Jira tests): the cart, the
  Checkout button, the checkout pages and their forms and the order overview are tested on any authorized website;
  the button that places the order or pays (Finish, Place order, Pay now, Confirm order ...) is never pressed
  - the test is Blocked at that step with the reason. Payment pages / providers, deleting and logging out stay
  protected in every mode; built-in tests and the crawler are unchanged.
- "Demo shop - allow placing the order" (Execution Center, requirement-based runs only): for a demo / test shop with
  no real order or payment, test cases may also finish the demo order - through the engine's existing permission
  (staging + `ALLOW_ACTIONS=pay` + test payments, this run only). Without it such a case is listed as not run, with
  the reason. Taking an item out of the test's own cart is no longer treated as destroying data.
- A requirement-based run no longer also runs the built-in site-wide checks (`test_site.py`, `test_all_links.py`);
  they belong to autonomous / hybrid runs (the Agents panel showed "25 tests, 12 failed" next to 3/3 passed).
- A Jira test case is not asked about again in the engine's staging review (it was reviewed in the workspace).
- "... is not shown" is a security rule only for passwords, tokens, card numbers and personal data (a cart badge
  that is not shown is not).

## 2026-11-26 - Jira executions no longer run without an AI and call it "Complete"

- Root cause of "Not automated: your own tests need an AI ... choose an AI in the chat" (reproduced): the Execution
  Center sent no AI choice by default; the server then used `.env`'s `LLM_PROVIDER` (a cloud AI) while privacy was
  local-only, and `privacy.select_provider` turned it into `none` without an error; nothing checked before the run,
  so every requirement test was 'Not automated' and the execution ended 'finished'.
- `backend/execution_preflight.py` + `POST /api/requirements/executions/preflight`, also enforced by
  `POST /api/requirements/executions`: the AI the engine will really use and whether it is ready (privacy, key, local
  model), the target address and authorization, and one headless visit with the run's own Chromium (the browser
  starts; a visible password box means a test account is needed). Nothing is created when a blocking problem is
  found; each problem has a recovery action and the selection is kept. The checked AI is the AI the run gets.
- Execution Center: AI provider (every supported provider with its real readiness), model (the provider's models, no
  hard-coded one) and an optional key for the run are in the main form; "Allow cloud AI" uses the existing privacy
  setting with an explicit agreement.
- Outcomes apart from lifecycle: "Execution unsuccessful - no tests were automated", "Completed with failures",
  "... some test results need review", etc., with counters from stored results (selected, actually executed, passed,
  failed, requires review, blocked, not automated), automation coverage and pass rate. A failure the engine itself puts
  on the generated test ("test mistake", "test-script defect") is "Requires review", not a failed requirement.
- Test ideas: no generic "Security around" idea (only a security rule the criterion states); AI ideas that repeat a
  rule idea, or negative / security ideas without a basis in the criterion, are dropped.
- Test cases record their Jira work-item kind; a reproduced Jira Bug is triaged "reported bug reproduced" and never
  proposed as a new defect.
- Evidence: real guided runs on www.saucedemo.com (OpenAI via the Execution Center): QPL-2 4/4 and QPL-3 3/3 passed
  with real assertions; see docs/REQUIREMENTS_INTELLIGENCE.md.

## 2026-11-26 - Live Execution shows every browser and every running execution

- The Live view followed only frames an event marked, and only the newest one or two browsers; test workers (`gw0`,
  `gw3` of a real run) save their screen without such a mark, so they never appeared. A new route
  `GET /api/runs/{job}/live` lists the run's real screens with their change time: every browser is shown (test
  browsers first) and a screen is reloaded only when its file changed.
- Another running execution (a re-run, another tab's run) is offered under "Also running" in the Live view.

## 2026-11-25 - Pages scroll again; connect more than one Jira site safely

- No Jira workspace page (and not the Accuracy lab) could be scrolled: `studio.css` locks `html, body` for the chat,
  whose thread scrolls inside, and these pages load it too. Pages laid out as `.lab-shell` scroll as a whole again.
- Integrations shows every Jira (and Confluence) connection and a "Connect another … site" card; the import wizard
  offers each connection.
- Security: all Jira connections shared one token slot, and changing a connection's address kept its token, so a
  token saved for one Atlassian site could be sent to another. A second site gets its own slot
  (`JIRA_<ID>_SITE_TOKEN`); a connection whose site or account changes loses its saved token (audited, the page
  asks for the new one); and a stored token is bound to its site (`credentials.site_of`) and never handed out for
  another.
- The Execution Center's website lookup no longer clears an address typed while it was still answering.

## 2026-11-24 - Ported from branch claude/laughing-wright-yvr79d (74e5000)

- Frame forms are numbered after the page's own by one tested helper (`renumber_frame_forms`), replacing the inline
  WIP renumbering, so `form<N>` names one form and the footer Subscribe form is never sent by an empty-form check.
- A header or sidebar search box is again a field of its own search form (still left out of other forms), so the
  search results page is discovered.
- A control recorded under a borrowed label is resolved by its own recorded selector.
- "Nothing found" is read in the page's shown content only (`SHOWN_MAIN_TEXT_JS`): the header cart's "0 ITEMS" and
  hidden "No results" templates no longer count.

## 2026-11-24 - Jira workspace: one guided test from requirements to report

- "Requirements" is called "Jira" in everything a person reads (Studio and Lab links, page title, breadcrumb);
  routes, APIs and identifiers are unchanged. The sidebar group has the 15 items in workflow order, collapses,
  scrolls on its own, has icons and ✓ marks taken from the stores.
- Guided workflow: step indicator, Back / Next, a server-side draft per person (`backend/atlassian/workflow.py`,
  `/api/requirements/workflow`), Import & Continue, Analyze Selected / All, bulk review, Generate Test Cases, Run
  Selected Tests, the Live Execution view opening by itself, View Report.
- New Test (six options) starts a fresh draft and keeps every earlier execution and report.
- Target detection with sources (saved target, earlier execution, requirement text), the four outcomes, a
  reachability check classifying DNS / TLS / timeout / connection / availability problems
  (`backend/target_check.py`), saved targets per Jira project with an optional test account kept in the owner-only
  credentials file and reused only for the same address.
- Live Execution: sticky header and controls, independently scrolling panels, auto-follow that pauses when the log
  is scrolled up, "Jump to latest", frames loaded only when the run recorded one. Reports: one record per run,
  counts, per-case results, screenshots, Rerun Failed, Run Impacted, Export.
- Specific rule-based scenarios (e.g. "Verify sorting by Price (low to high)" with real steps); negative ideas only
  for stated constraints. A test whose login / precondition / environment prerequisite failed is Blocked, not Failed.
- Found in the live QPL-3 SauceDemo run and fixed at the cause: the script writer dropped client-rendered 404
  pages (SauceDemo's inventory), so the AI got no page and invented `https://example.com/...`; it now uses
  `page_testable`, refuses to ask without a page, gives the AI the observed item cards, and grounding refuses
  `goto` to unexplored hosts, unseen `.class` selectors and `guest` on logged-in cases. An off-site navigation is a
  test-script defect, never Blocked.
- Tests: `tests/test_jira_workflow.py` (24) and updated `tests/test_requirements_ui.py` (19).

## 2026-11-24 - Requirements Intelligence, Phase 5 (defects and controlled Jira write-back)

- `backend/atlassian/defects.py`: defect records from real requirement-test failures - one per test case and failure
  signature, triaged from the engine's failure analysis, resolved / reopened (regression), dismissible with a reason.
- `backend/atlassian/writeback.py`: proposals (results comment per story, Bug linked to its story) with the exact
  request stored as a preview; approval by a named reviewer (`jira_write` approvals); sending only when the server
  owner allows it (`QPILOT_JIRA_WRITEBACK=1`), the workspace switched it on and a separate `JIRA_WRITE_API_TOKEN` is
  stored; idempotency key + marker read back from Jira before any send or retry; full audit.
- `client.WriteClient`: the only writer, limited to creating an issue and adding a comment; no blind retries.
- API routes for defects and write-back; Studio screen "Defects and Write-back"; traceability rows end with defects.
- Tests: `tests/test_requirements_writeback.py` (8) and a browser test. Writes stay off; nothing was written to a
  real Jira.

## 2026-11-24 - Requirements Intelligence, Phase 4 (requirements to execution, websites)

- `backend/atlassian/bridge.py`: test cases from accepted ideas (`TC-<KEY>-<n>`, versioned, fingerprinted,
  stale when the requirement changes), edits that need a named reviewer's approval, executions and results, the
  traceability matrix and executed coverage (planned, executed and passed kept separate).
- `backend/requirement_tests.py` + `test_design.py`: a run takes approved requirement test cases
  (`QA_REQUIREMENT_TESTS`); requirement-only or hybrid strategy; a case without working steps is "Not automated",
  never Passed.
- API: test-case generate / list / edit / approve, executions start / list / live / cancel, `traceability`,
  `coverage/execution`. Capabilities now report generate, run and traceability as available; write-back stays off.
- Studio: Test Case Builder, Execution Center, Live execution, Test evidence, Traceability (CSV export), executed
  coverage, the drawer's Test Cases / Execution Results / Traceability tabs, next actions in the Review Center.
  Fixed duplicate element ids (`exType`, `exStatus`) between the explorer and the execution form.
- Fixed: an engine "Skipped / Not automated" case was counted as executed.
- Tests: `tests/test_requirements_execution.py` (17) and a Phase 4 browser test; three tests that checked the
  old "Upcoming" placeholders now check the working screens.

## 2026-11-24 - Test pollution and a lost slow page fixed

- Tests that load `backend/templates/conftest.py` in-process now use the `template_conftest` fixture
  (`tests/conftest.py`), which restores Playwright's `Page`, `Locator`, `APIRequestContext`, `SyncBase` and
  `pytest.qa_step` afterwards. Four tests no longer skip ("Blocked: checkout or payment") depending on which worker ran
  first. An autouse check fails any test that leaves Playwright patched.
- Discovery bug (`backend/payment_nav.py`): when a slow page's first load timed out, the checkout guard answered the
  already-settled request again; Playwright passed "Route is already handled!" to the retry, so a page that opened was
  reported as failed or lost. Such a request is now left alone (other routing errors still surface). Under load the
  busy-server test went from 7 failures in 40 runs to 40 of 40 passing.
- Non-slow suite without `.env`: 2430 passed, 0 failed, 28 skipped (all for services not running here or Windows-only).

## 2026-11-24 - Requirements Intelligence, Milestone 3 (Studio workspace, part A)

- New Studio page `/requirements` (sidebar link from Test studio and Accuracy lab): Overview, Integrations, Import
  wizard with preview and selection, Requirements explorer with detail drawer, Review center, Confluence explorer,
  Sync history and audit. Unavailable actions (test generation and runs) are labelled, not buttons.
- API: `GET /api/requirements/reviews`; a review may accept with corrections (`edit`), keeping the original and
  marking a changed outcome as inferred; `can_review` follows the role.
- Fixed: the item list read the Confluence space from the wrong field.
- *9 browser tests (real server, mock site) and 4 API tests.*

## 2026-11-24 - Requirements Intelligence, Milestone 2 (import modes and the Studio API)

- Import modes: incremental (with `new_keys`, `changed_keys`, affected requirements, cancel and resume), full (any
  work-item type; missing items kept), targeted by keys or work-item links (optional sub-tasks, parent, linked items
  and linked Confluence pages; never changes a project's cursor or marks other items missing).
- Filters: epic, sprint, status, priority, assignee, labels, created / updated dates, summary words and extra JQL
  (quoted, bracket-balanced, no project clause, checked by Jira's read-only JQL parser).
- Preview with new / updated / unchanged per item and an estimated total; import results with criteria found, needs
  analysis, duration and last success; sync history (`sync_runs`).
- `/api/requirements/*`: connections, write-only tokens (DPAPI-encrypted file; `.env` only for the local tenant),
  connection test, projects, types with counts, spaces, JQL check, preview, background imports with progress and
  cancel, history, requirements explorer, details, versions, analysis, signed reviews, coverage, overview, audit,
  capabilities (Phase 4–5 actions reported as not available). Login, roles and tenant isolation on every route.
- *48 new tests, local mock only.*

## 2026-11-24 - Requirements Intelligence, Milestone 1 (audit findings fixed)

- Criteria: `AC1:` / `AC-2 -` / `Acceptance criterion 3:` lines without a heading; heading and custom-field variants
  (`AcceptanceCriteria`, `Acceptance Criteria (AC)`, `ACs`, `Definition of Done`, inline `Acceptance Criteria: …`);
  Notes / References / Out of scope and other labels end the criteria. A plain numbered list without a heading is
  still not taken.
- Work-item types: `Connection.work_item_types` (default Story), discovery with counts, and a warning naming the
  project's real types when an import finds nothing. `python -m backend.atlassian types` shows them.
- Credentials: read connections use `JIRA_READ_API_TOKEN` / `CONFLUENCE_API_TOKEN`; `JIRA_API_TOKEN` (defect
  creation, which writes) and other products' keys are refused. Every `JIRA_* / CONFLUENCE_* / ATLASSIAN_*` secret
  name and every saved `token_ref` is redacted and kept from test workers. Validation errors never echo the input.
- Writes: the Atlassian client refuses every non-read request; the command line warns when the older defect
  creation is configured to write.
- Reviews: deciding a requirement suggestion through `POST /api/approvals/{id}/decide` updates the stored analysis,
  records the signed-in reviewer (`decided_by`), refuses shared tokens and other tenants; `POST /api/approvals` refuses
  `requirement_suggestion`; a queue row not created by analysis cannot decide a suggestion.
- New read-only command line: `check`, `connect`, `projects`, `types`, `sync`, `show`, `analyze`, `spaces`,
  `sync-space`. Documentation inconsistencies from the audit corrected. *84 new tests, local mock only. Non-slow
  suite 2367 passed, 0 failed, 29 skipped; lint clean.*

## 2026-11-23 - Fixed the five baseline test failures

- Discovery finds header search boxes (kept as `search_fields`), numbers iframe forms after the page's own (no more
  duplicate `form1` and `StopIteration` in script generation), and never names a box after another box's label.
- `test_classic_shop.py` enables data tests in both fixtures; `test_end_to_end.py` sets its own sample size instead
  of relying on the developer `.env`, and finds the repaired test by its control rather than by number.
- No assertion weakened or removed. Verified without `.env`: classic shop 9 passed, end-to-end 4 passed, deep test 3/3
  on repeat, non-slow suite 2284 passed / 28 skipped, lint clean.

## 2026-11-23 - Requirements Intelligence, Phase 3 (requirement analysis)

- Acceptance criteria copied by rules from Jira (custom field, description, numbered / bulleted lines,
  Given/When/Then) and linked Confluence sections (lists, must/shall sentences, tables, Gherkin), each with its
  source, version, locator and quote; unautomatable criteria marked with the reason.
- Ambiguous, incomplete, duplicate, contradictory and missing criteria; Jira vs Confluence conflicts with both
  quotes (rules only).
- Positive / negative / boundary / security test ideas, explicit or inferred, each an item in the existing approval
  queue (new kind `requirement_suggestion`); optional AI ideas only when the privacy settings allow it, grounded
  against the criteria (unknown criteria and invented records refused, unquoted outcomes marked inferred).
- Per-criterion coverage (covered / uncovered / ambiguous / blocked / pending review), stale detection, audit and
  analysis history, tenant isolation. *Tested with mock data and a stub AI (22 tests); no live evidence.*

## 2026-11-23 - Requirements Intelligence, Phase 2 (read-only Confluence and story links)

- Confluence Cloud spaces and pages (v2 API) through the same read-only client: storage format to sections with
  heading paths (paragraphs, nested lists, tables, tasks, code), requirement-like sections marked, links to pages and
  Jira issues found, malformed and very large pages handled, Confluence's own version numbers kept with every old
  version.
- Incremental, resumable space sync; linked-page walks with depth and page limits (circular, inaccessible and deleted
  pages handled); a Jira story linked to the pages that specify it (remote links, description, page mentions).
  *Tested against a local mock Atlassian site (24 tests); not yet against a real site. No AI used.*
- Baseline: the re-run of the pre-existing failures gave 4 failed, 9 passed (one of the five is intermittent).

## 2026-11-23 - Requirements Intelligence, Phase 1 (read-only Jira connector)

- Read-only Jira Cloud client (retries, Retry-After, 401 = expired token, no redirects, size cap, redacted errors),
  project discovery, paged JQL search (`/rest/api/3/search/jql`), ADF to text, story normalization with a content
  hash, a tenant-scoped SQLite store with every source version, and an incremental, resumable, audited sync.
  *Tested against a local mock Jira (26 tests); not yet against a real Jira site.*
- `CONFLUENCE_API_TOKEN` is redacted like the other secrets and blanked for local-only test workers.

## 2026-11-23 - Requirements Intelligence, Phase 0 (design only)

- Design for reading Jira Cloud stories and Confluence Cloud pages as requirements, with cited acceptance criteria,
  review, runs on the existing engines, persistent traceability and approved Jira writeback:
  `docs/REQUIREMENTS_INTELLIGENCE.md`.
- Data contracts with their safety rules (`backend/atlassian/models.py`) and 24 unit tests. *Unit-tested; no
  Atlassian connection exists yet.* No existing behavior changed.

## 2026-11-22 to 2026-11-23 - AI-assisted testing, form values, Android tester checks, safety fixes

Status words below: **verified** = proven in a real run; **unit-tested** = covered by tests, not yet proven in a
real run.

- AI-assisted testing (option 02) runs inside Studio: **Run it here with Qpilot AI** opens the shared settings
  (account, AI model, pages) and starts the run with the typed request as the run's own tests. Connecting an external
  MCP assistant is optional. *Verified (OrangeHRM, OpenAI).*
- Your own tests steer the run: matching pages are explored first (optionally only them), the AI writes a plan
  (navigation, preconditions, steps, assertions, unknowns), destructive requests are refused, vague ones ask for
  clarification, and the report has a **Your request** section. *Verified (OrangeHRM PIM).* The AI-written PIM search
  test passed on the live site on its own; *inside one complete run it is not yet proven*.
- AI test code is checked against what the page really showed: unobserved selectors and guessed row counts are
  refused; table rows reach the AI as {column: value}; row checks wait for new results. *Verified (live PIM search).*
- Forms are filled like a tester: real field labels, stable addresses, values that fit each field (IDs, addresses,
  phones, dates in the page's own format, realistic names new every run), picking from suggestion lists and custom
  dropdowns, tables built of divs. *Verified (OrangeHRM: 0 "keep the typed text" failures, was 9).*
- Android: your tests run first (up to 10 lines) and a placeholder journey is "not automated", never a pass;
  a control repeated on every list item is checked once ("sampled"); the network-off check and tap-to-return after
  background. *Verified (My Demo App, CartNShop on an emulator).* One-time codes typed by a person in Studio, deep
  links, dark mode / 130% font / German layout checks, device-only features marked "not testable here" on an
  emulator, cold start and memory, sign-up error text + screenshot. *Unit-tested.* Clearing the app's data before a
  run is opt-in (`fresh_start`).
- Safety: in test / production the "empty form" and "wrong e-mail" checks no longer send the form (it is stopped in
  the browser); Enter in a text box is judged like a click on the form's own button; admin and seller tools (Add
  Product, Sold Products) are never pressed. *Verified (classic-shop safety test).*
- Link checks work behind an HTTPS proxy. The test suite no longer overwrites `docs/ops-evidence/android_adb_probe.json`.
- Dependencies: PyJWT 2.15.1, certifi 2026.10.18, opentelemetry-api 1.45.2 (pip-audit: no known vulnerabilities).
- Known open items: 5 older test failures (`tests/test_classic_shop.py` x3, `tests/test_end_to_end.py` x2); see the
  audit linked from issue #22.

## 2026-11-17 - Remaining Qpilot X rules

- The large-listing sample is unchanged: a listing still opens the configured few products and leaves the rest, and checkout and payment stay blocked.
- At the end of a run the same rules are applied to that run's pages, failures, roles, and optional spec, locale, journey, plugin, and planted-defect files. The decisions are stored in `qx_applied.json`. The run's verdict is not rewritten.
- The report also runs the section 22 row in order: authorized target, resumable inventory, graph, isolated workers, seeded defect, the six separate counts, and the operation checks.
- A run now stores that registration in `target.json` before the crawl. A stopped crawl keeps its inventory and remaining pages, and resume continues from them. Execution writes `workers.json` for the cases that have a trustworthy assertion.
- Each later stage stores its own row step, in order: inventory, graph, workers, seeded defect, the six dashboard counts, and the operation checks.
- The live run now applies the remaining rules in place: role sessions, environment controls, locale sample, schema diff, plugins, worker test data, dependency faults, replay packages, mutation score, journeys, evaluation, and trends.
- The crawl orders ordinary links by the next-page score, writes the locale facts a page actually showed, and saves an OpenAPI spec when one is found. A checkout page is still opened so its pay button can be recorded as blocked; it is not preferred over ordinary pages. A fixed clock, a network fault, or a dependency fault reaches the test browser only when that run asks for it. Payment, delete, and logout stay blocked.
- An accepted plugin assertion is written as a test. A workflow whose API spec changed is not turned into a trusted test. When a stub is asked for, a faulted call gets a JSON stand-in instead of only failing. `python main.py --replay RUN_ID` shows the saved steps and runs the test again when the package names one.
- Each worker's synthetic records stay ready while the tests run. A form tag uses that worker's own account record. The records are marked cleaned after the browsers stop.
- The finished report in the studio shows the six Qpilot X counts: discovered, tested, passed, failed, blocked, and unknown.
- A new test on Standard shows a Swarm card in the chat. A large product list gives 3 products to the workers. An older run in the sidebar stays as it was.
- An unanswered sensitive case stays unrun. A locator repair remains a proposal and keeps the original error. A plugin cannot turn off authorization, secret redaction, payment, delete, or logout. Production does not get environment controls or dependency faults.

## 2026-11-17 - Swarm test data per worker

- When a large listing is sampled, each worker that receives a product gets its own synthetic account, cart, and order.
- Those records are tagged with the run id, start from a known reset, and are cleaned up only for that run.
- A production environment and a real customer email are refused. The plan is stored on the crawl under `swarm.data`.

## 2026-11-16 - Remove leftover documentation

- Removed the phase notes in `docs/`, the live-run write-ups in `deep_validation/`, and the duplicate essays, diagrams, and sample copies in `project-docs/`.
- The product docs that remain are `README.md`, `DEPLOYMENT.md`, `SECURITY.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`, `STATUS.md`, and the short folder guides.
- Contract examples the Studio loads stay in `demo-apps/`.

## 2026-11-16 - Android dynamic recovery

- Ordinary content waits use `dynamic_wait_s` (1–20 seconds, default 12). A stuck tap or Chrome page load gives up after 20 seconds. A splash screen still has 30 seconds. A shop page is not held open until ads and analytics go quiet.
- One recovery path for Android Chrome and native apps: handle one exact safe popup, tap, and retry a stale or covered control once.
- Dismiss only an exact Close, Dismiss, Skip, Not now, Maybe later, No thanks, Cancel, or X. Any other popup needs an approved `overlay_choices` entry, and a protected target is rejected.
- A blank page is not a successful launch. A security check pauses for the person and does not count as the shop.
- A production run does not add to the cart or log in. A structural locator cannot change data unless the contract names that control.
- Screen signatures ignore flickering prices, ad ids, and carousel text, and still include a popup.
- `summary.json`, `progress.log`, and `dynamic.json` record the source, device, locator, retry count, overlay text, and blocked reason. Credentials stay out of those files.

## 2026-11-15 - Workspace naming and cleanup

- Use `Qpilot` for the local checkout, controlled APK filename and Java fixture source package.
  Preserve the prebuilt APK's original package/checksum and legacy client compatibility.
- Remove committed Gradle machine caches and superseded proposal, implementation-update and review documents; update remaining references.
- Retain distinct report rebuilds and linked run evidence. Remove unreferenced recordings, sampled video sheets and disposable preview/test caches.
- Document MCP checkout paths, Studio connection and the need to reconnect a running client after moving its checkout.

## 2026-11-15 - Native Android exploration coverage

- Distinguish routes that share one Android Activity, while allowing stable app controls to identify a screen when volatile backend error text changes.
- Name native screens from stable selected-tab, semantic-heading, form-action and search semantics when apps expose accessibility labels instead of text views; use those labels in route identity while filtering greetings and volatile labels.
- Treat zero discovery scrolls as until exhausted within a 100-gesture hard cap. Infer vertical `ScrollView` orientation, explore horizontal viewports, probe unknown axes, and use recorded bounds when a scrollable node has no unique locator.
- Count restoration gestures inside the scroll cap, continue to the other axis when a probe cannot read movement, and ignore changing backend request IDs, including IDs embedded in loading labels, in scoped viewport signatures. Use visible bounds when a unique scroll container lacks its own bounds. Verify viewport changes and restoration; report unknown movement, incomplete scrolls and unvisited controls instead of silently treating them as covered.
- See [Android exploration and testing limits](docs/29_ANDROID_FEATURE_EXPANSION.md) and [real-user Android test limits](docs/30_TEST_LIKE_A_REAL_USER.md).

## 2026-11-15 — Native Android form reliability

- Use native geometry and shared ancestry to distinguish one submit button below
  the fields from form-mode selectors above them, following the live WebdriverIO
  run; retain ambiguity when several lower submissions or missing bounds remain.

- Recognize an unambiguous safe primary submission button with an unfamiliar label and scope inputs to its container.
  Protected actions, Cancel and ambiguous submissions remain excluded from automatic fallback.
- Group standard native Spinners and radio selections with the form. Observe and verify dropdown choices rather than
  generating a separate navigation workflow for each country. Guided flows also support approved native selection.
- Preserve Android validation Toast text from the immediate UIA snapshot while filtering other system UI; reduce UIA's
  idle wait so short-lived messages remain verifiable. Form destinations that contain lists now enter product/item
  and screen-control exploration.
- Require a destination or non-error success result for native positive submissions. A disappeared form or an error
  message cannot establish success. Preserve verified form setup when exploring the resulting screen.
- Reject AI submissions without recognized-form input setup. Recognize recorded UiAutomator/ADB transport losses and
  propagate interrupted input without values or blind submission retries.
- See [implementation, operation and verification limits](docs/36_ANDROID_NATIVE_FORM_RELIABILITY.md).

## 2026-11-14 — Shared MCP configuration and Qpilot naming

- MCP setup reuses Standard account, provider/model/key, exploration, expected-result and approved-flow controls.
  Android settings move between workflows without duplicated IDs; Web opens the existing configuration form.
- Studio prepares an exact private configuration in memory for 15 minutes. The new `start_prepared_test` tool
  consumes its opaque reference with explicit permission, checks current privacy, and uses the existing launchers.
  Preparation starts no automation. Android startup prepares installed local Appium and the selected emulator.
- Credentials stay out of copied requests/storage and are discarded from the preparation store after startup/failure.
  Edits revoke the reference, expiry/restart invalidates it, and successful repeat starts return the same job.
- Public UI, report/launcher/package names, current example references and guides use Qpilot. `QPILOT_*` references
  are preferred; legacy saved contracts, clients and installed-tool paths remain compatible and redacted.
- Reviewed documentation, corrected stale limitations/deferrals, regenerated the contract schema and Android setup
  illustrations, and checked local document links.

## 2026-11-13 — Evidence linkage + run-time reserves (P9 / P6)

- Findings from `ensure_findings_from_results` / classify retain control/container, URL/state, expected vs
  observed, screenshot, and console/network notes (secrets still redacted).
- Console JS noise and failed resource loads without an `AssertionError` classify as infrastructure — not
  auto `product_defect`. Crawl findings separate app JS exceptions, resource-load failures, and readiness
  timeouts; own-host HTTP error status stays a product signal.
- Session expiry / protected reauth (`LOGGED_OUT`) is inconclusive with `session_expired`, distinct from
  credential `auth_problem`. Blank/still-loading readiness timeouts are explicit `timeout` findings.
- `ANALYSIS_RESERVE_S` / `REPORT_RESERVE_S` (defaults 180/120): near `RUN_TIME_LIMIT_MIN`, stop heavy discovery
  and new suite starts so analysis + report still finish. Measure phase durations before raising defaults.
- Observe deprioritizes global chrome / table-row toggles (KIND_CAP unchanged). Resume keeps completed results
  and runs only pending tests. Docs note serial watched Chrome vs parallel `TEST_WORKERS`.
- Offline: `tests/test_orangehrm_p6_p9.py`.

## 2026-11-13 — Field-aware data, verification credit, AI grounding (P3–P5)

- Field-aware values from labels/constraints (`field_kind`): valid email/phone/numeric/date (type/format/pattern).
- Custom checkbox/radio/select: prefer user-facing click/select; verify retained checked/value; re-resolve after
  reactive updates; force/DOM only as recorded fallback (`proves_user_actionability=False`).
- Unsubmitted form / input-only cases carry `verification: interaction` — strong fill asserts never grant
  business-verified credit (registry → smoke with an interaction why).
- Search/filter/sort/pagination and submitted form/CRUD keep `verification: business` when outcomes are defined.
- Writes stay gated by staging + `writes_ok` / `ALLOW_ACTIONS`; `environment=test` alone never enables writes
  (`write_authorization_gap` names the missing permission).
- AI grounding rejects invented records (e.g. John Doe), brittle toast wrappers, and unobserved headings;
  unsupported scripts are exploratory/unsupported before execution — not product defects. Role-based tables OK
  without native `<table>`. Healing still refuses assertion removal.
- Offline fixtures: `tests/test_orangehrm_p3_p5.py` (+ existing form-boundary / ai-grounding tests).

## 2026-11-13 — Form boundaries and target identity (P2)

- Form fill/assert scopes to the form, dialog, or labeled section; prefers label / role / stable id.
- Ambiguous matches are fail-closed (automation/inconclusive) — no silent Playwright `.first` pick.
- Sidebar/global search and unrelated table row checkboxes are excluded from form schemas and fill targets.
- Opener paths (Add dialogs, nested menus) stay on form cases; missing/invisible required fields block a whole-form pass.
- Offline fixtures: sidebar Search vs Emergency Contact phone, duplicate-label containers, unresolved ambiguity, wrong opener.

## 2026-11-13 — Coverage gate honesty + Pay Grades vs payment

- Route/feature gates no longer claim exhaustive reachability when exploration is partial
  (`not_tried_limit`, pending URLs, crawl/time limits); prose keeps URLs / route patterns /
  controls / interaction checks / features / workflows and PASS–INCONCLUSIVE denominators separate.
- `metrics.consistent` failures lead summary reasons and the HTML report; provisional/untriaged
  findings keep Insufficient Evidence instead of “zero bugs / none found”.
- Admin config navigation named “Pay Grades” / “Pay Grade” (link/menuitem/tab) is not classified
  as `pay`; real Pay now / Proceed to payment / checkout submits stay blocked, with reasons that
  name `ALLOW_ACTIONS` / `TEST_PAYMENT`.

## 2026-11-13 — Findings finalize on interrupt / empty failures

- `ensure_findings_from_results` builds a rule-based finding for every failed/inconclusive result
  (idempotent merge into `failures.json`; LLM enrichment stays optional).
- Incomplete stop / fallback report paths ingest saved `results.json` / `.jsonl` before gates.
- Reporter and quality gates no longer pass automation-reliability or “no bugs” when failures
  remain unlinked; metrics consistency counts consolidated `nodeids`.

## 2026-11-12 — Studio UI refresh + delete harden

- Static JS/CSS served with `Cache-Control: no-store`; home page shows a visible **build** fingerprint.
- `GET /api/ui-build` returns frontend digests so you can confirm `git pull` + `ui.bat` restart worked.
- Recent **Delete** is always labeled; click does not open the run; server retries folder removal (Windows locks).

## 2026-11-12 — Repo-fix: scan summary and “what you have to do next”

- After a web report, **Apply fixes** still appears when code-bearing findings exist.
- Paste a GitHub link → **Prepare changes** (or Enter): validates `github.com/owner/repo`, scans the repo,
  shows files scanned / matched / hand fixes / advice-only, then an ordered **What you have to do next** checklist.
- `repo_fix.prepare` returns `files_scanned`, `fixes_considered`, `fixes_total`, and structured `no_code` items.

## 2026-11-12 — Studio MCP Android parity, Standard budgets, delete/history

- Android MCP panel mirrors Standard essentials: device + Refresh, Appium URL, optional activity, test-build and
  ownership checkboxes, apk/installed/web (APK as path string). Prepare request includes `get_android_environment`
  then `start_android_test` fields; Standard↔MCP values sync where possible.
- Web Standard intensity reset drops Thorough-forced full/site/80; `explore_repeated_controls` no longer follows
  full crawl alone; server applies Thorough budgets only when `thorough=true` is explicit.
- `/api/history` lists incomplete runs (no `summary.json`); DELETE still removes the runs folder; Recent delete
  control stays visible and clears the open chat after a successful delete.
- In-UI MCP help blurb + short note in `docs/15_MCP_INTEGRATION.md`.

## 2026-11-12 — Thorough mode raises real per-run budgets

- `RunRequest.thorough` raises this-run budgets: repeated controls, ≥80 actions/page (cap 100), ≥60 min crawl,
  ≥500 test cases, `PATTERN_SAMPLES=0`, `QA_THOROUGH=1` (also when full crawl + `explore_repeated_controls`).
- Studio defaults intensity to Thorough; coverage gaps show not-tested counts and **Run Thorough again**.
- MCP `crawl_website` / `start_web_test` default `max_pages=0`, depth 12, and post Thorough fields.
- Coverage honesty: optional `meaning: scripted` + notes that scripted ≠ business-verified; Excel status values unchanged.
- Docs: `docs/31_PERFORMANCE_AND_LIMITS.md`, `STATUS.md`. Coverage remains finite — not every component on every site.

## 2026-11-12 — Live MCP AI-assisted Android test

- Exercised real stdio MCP client against Studio: 11 tools, privacy consent, Sauce MDA Android run.
- Run `android_20261112_105018_1e0c72`: 38 passed, verdict Insufficient Evidence (honest gates).
- Mapped MCP `BridgeError` → `ToolError` so assistants see actionable errors.
- Evidence: `deep_validation/live_runs/mcp_ai_assisted_test_20261112.md`.

## 2026-11-12 — Keep main only; trim deep_validation archive

- Keep production docs: `CHANGELOG.md`, `CONTRIBUTING.md`, `STATUS.md`.
- Slim `deep_validation/` to README + evidence index + `live_runs/*.md` (drop historical phase write-ups).
- Delete merged remote feature branches; only `main` remains as the working branch.

## 2026-11-12 — Docs cleanup + MCP/AI hardening

- Replaced root `FINAL_*` / phase checklist sprawl with a single [`STATUS.md`](STATUS.md).
- Removed raw `deep_validation` pytest dumps and live `.log` files from git; kept markdown assessments.
- Fixed `ask_llm` when `LLM_PROVIDER=none`: clear “AI is turned off… rules are used” error.
- Documented optional MCP install (`requirements-mcp.txt`); verified MCP server registers 11 tools after install.
- Trimmed one-off session review docs under `docs/`.

## 2026-11-12 — Production Git governance

- Expanded `.gitignore` (Android/Gradle locals, artifacts, tool caches, `.claude/`).
- Removed tracked Claude agent metadata (`.claude/agents/*`); guardrails live in `ARCHITECTURE.md`, `.cursorrules`, and `.github/copilot-instructions.md`.
- Updated `README.md` (features, stack, repo tree) and `CONTRIBUTING.md` (branching, Conventional Commits, PR checklist).
- Confirmed `.env` remains untracked; secrets stay in local `.env` / `.env.example` placeholders only.
- No mass split of oversized pipeline modules in this pass (documented for follow-up).

## 2026-11-12 — Thorough exploration preset + ecommerce contract example

- Website setup: **Exploration intensity** Standard / Thorough. Thorough sets full crawl (`max_pages` 0), site scope,
  repeated-control exploration, and at least 50 actions per page; helper text names HARD_PAGE_CAP / time budgets.
- Finished chat reports show a short **Coverage reminder** when not-visited, limit-reached, blocked, or not-tested gaps appear.
- Added `project-docs/examples/ecommerce-web-contract.json` (search → product → add to cart; flows unapproved templates).
- Docs: `docs/17_CLEAR_SETUP_AND_CRAWL_AUDIT.md`, `project-docs/13_ADVANCED_QA.md`. Existing APIs/workflows unchanged.

## 2026-11-12 — Phases 14–16 documentation / hygiene

- Added `docs/31_PERFORMANCE_AND_LIMITS.md`: known config caps (`MAX_PAGES`, `HARD_PAGE_CAP`, workers, timeouts, sandbox) and **measure before optimize**. No invented benchmarks.
- Updated `DEPLOYMENT.md`: Windows remains the primary install/CI target; Linux noted for offline/regression exploration only; light install troubleshooting table.
- Updated `PROJECT_IMPLEMENTATION_STATUS.md`, `MASTER_TODO.md`, and `FEATURE_VERIFICATION_MATRIX.md`: Phases 6–13 marked **IMPLEMENTED**, **not VERIFIED** (full suite deferred by owner), covering Phase 6 env/locator, Phase 7 UX, Phase 8 API, Phase 9 repo-fix partial-match, Phase 10 LLM/MCP errors, Phase 11 security, Phases 12–13 reporting honesty.
- Status vocabulary used: **IMPLEMENTED** / **not VERIFIED** (plus existing historical/partial language). No row claimed **VERIFIED** without test evidence.
- No application logic rewrites; no `.venv` recreated; no runtime artifacts deleted.

## 2026-11-12 — Phases 6–13 implementation slices (code; recorded for status hygiene)

Prior commits on this branch (not re-verified as a full suite here):

- Phase 6: Android environment readiness and native/WebView locator boundary messages.
- Phase 7: Frontend empty/error states and basic a11y.
- Phase 8: API 404s for missing stop/review; `exit_code` on ended jobs.
- Phase 9: Repo-fix partial-match reporting for multi-tag findings.
- Phase 10: Offline AI provider and MCP error-message hardening.
- Phase 11: Safety controls for metadata, private artifacts, and uploads.
- Phases 12–13: Reporting honesty remains code policy (counts from run files; Incomplete → Insufficient Evidence); not a fresh accuracy VERIFIED claim.

## 2026-11-12 — Thorough exploration + ecommerce contract

- UI: Standard/Thorough exploration intensity; Thorough forces full crawl budgets, repeated-control exploration, and ≥50 actions/page; coverage reminder when pages/features were not visited/blocked/not tested.
- Added `project-docs/examples/ecommerce-web-contract.json` template and `demo-apps/ecommerce-web-contract.json` (Automation Exercise search/cart) exposed via `/api/contracts/examples`.
- Documented Thorough crawl knobs in `.env.example`.
- Live thorough run on automationexercise.com: 19 pages visited (pattern sampling), 0 not-visited within limits, 204 tests, 171 passed, verdict Not Ready (no login account; protected actions still blocked).

## 2026-11-12 — Phases 6–18 implementation + Linux Phase 17

- Implemented Phases 6–16 (Android env/locator, frontend UX, API contracts, repo-fix partial match, LLM/MCP errors, security, report clarity, performance/deploy docs).
- Phase 17 Linux non-slow regression: first run 6 failed / 810 passed; after fixes **816 passed**, 2 skipped, 65 deselected; ruff clean.
- Phase 18 delivery reports added: `FINAL_IMPLEMENTATION_REPORT.md`, `FINAL_TEST_REPORT.md`, `FINAL_SECURITY_REPORT.md`, `FINAL_COVERAGE_REPORT.md`, `FINAL_BENCHMARK_REPORT.md`, `FINAL_CHANGELOG.md`, `REMAINING_ISSUES.md`.
- Live Android/cloud LLM/GitHub/MCP sessions remain unverified on this host.

## 2026-11-12 — Phase 0 cloud re-baseline (docs only)

- Re-inspected the Git checkout on the Cursor Linux cloud agent (`/workspace`).
- Updated `PROJECT_IMPLEMENTATION_STATUS.md`, `MASTER_TODO.md`, and `FEATURE_VERIFICATION_MATRIX.md` to separate Windows historical Phase 0–5 evidence from this host.
- Added `deep_validation/13_phase0_cloud_rebaseline.md` with environment facts (Python 3.12 present, 3.13 missing, Git present, no ADB/Appium, no `.venv`/`.env`).
- No application source, tests, APIs, integrations, credentials, baselines, run artifacts or APKs were changed.
- Later phases remain gated pending owner approval; recommended next gate is a Linux Phase 1 regression re-baseline.

## 2026-11-10 — Phase 0 baseline documentation

- Added `PROJECT_IMPLEMENTATION_STATUS.md` with the inspected architecture, evidence status, blockers and repo safety state.
- Added `MASTER_TODO.md` with gated phases and the proposed Phase 1 sequence.
- Added `FEATURE_VERIFICATION_MATRIX.md` distinguishing implementation from fresh/historical verification.
- Added this changelog entry.
- No production source, tests, APIs, integrations, credentials, baselines, run artifacts or APKs were changed.
- Validation evidence remains as recorded in `deep_validation/`; current pytest results are blocked/inconclusive due Windows access-denied temp/process errors, and no current ADB device was available.

## 2026-11-10 - Phase 1 validation update

- Added `deep_validation/08_phase1_results.md` with current commands, results, and the incomplete regression status.
- Focused QA contracts passed using a dedicated directory under standard Windows Temp.
- Non-slow regression did not finish; the one surfaced failure passed when run alone and as part of its test file.
- No application code, tests, assertions, configuration, or existing runtime artifacts were changed or deleted.
## 2026-11-10 - Phase 1 completed

- Focused QA contracts: 23 passed with a dedicated standard Windows Temp basetemp.
- Serial non-slow regression: 751 passed, 65 deselected, exit 0; raw output is in `deep_validation/phase1-pytest-nonslow-serial.txt`.
- The parallel-only busy-server failure did not recur in isolated or full serial runs.
- No source, tests, assertions, configuration, or existing runtime data were changed or deleted. Git initialization remains deferred.

## 2026-11-10 - Phase 2 website discovery

- Fixed XML entity decoding for sitemap `<loc>` URLs and added a regression for query strings containing `&amp;`.
- Made the BigStore acceptance test explicitly set `PATTERN_SAMPLES=3`, matching its documented 3-full/10-smoke sample target for 2,000 slug-based product URLs.
- Verification: focused discovery tests 13 passed; BigStore 3 passed; serial non-slow suite 752 passed with 65 slow tests deselected; Ruff passed on changed files.
- The first BigStore attempt with sampling disabled hit its one-hour run limit and is retained as diagnostic evidence; the configured acceptance rerun passed in 3m21.84s.
- No existing feature or data was deleted; Phase 3 remains gated.

## 2026-11-10 - Phase 3 AI test generation

- Added a grounding check for exact quoted expected text in AI-generated website journeys and owner-authored AI tests. If the exact text is absent from observed site evidence and owner input, the case is marked exploratory and retains the original expectation for review.
- Grounded messages and owner-requested text remain unchanged; rules-only case generation is unchanged.
- Verification: AI test-design/grounding/case-optimization regressions 67 passed; final serial non-slow suite 754 passed, 65 deselected; Ruff passed on changed files.
- No live AI provider was contacted. See `deep_validation/10_phase3_results.md`; Phase 4 was gated at this point.


## 2026-11-11 - Phase 4 execution safety (in progress)

- Windows generated-test execution now fails closed if Job Object memory/process limits cannot be established; it attempts to stop the uncontained pytest process tree and reports an explicit error.
- Added regression coverage for Job Object creation and process-assignment failures.
- Made the sandbox trace regression independent of machine retry settings by explicitly requesting the retry the test asserts.
- Targeted checks passed: executor safety 2/2; sandbox/browser recovery 5/5; Android protocol file 3/3 in isolation; Ruff passed.
- Full serial non-slow run: 755 passed, 65 deselected, 1 Android mock test timed out at its 120-second action budget. The case passed alone and in three additional repetitions; its complete file passed in isolation. Phase 4 remains in progress; see `deep_validation/11_phase4_results.md`.


## 2026-11-11 - Phase 4 completed

- Final verification: executor safety 2/2; sandbox/browser recovery 5/5; Ruff passed; serial non-slow suite 756 passed, 65 slow tests deselected, 0 failed in 28:57.
- The prior Android mock timeout recorded 22,642 seconds on the monotonic timer. A full rerun with a temporary keep-awake request passed; timeout/assertions were unchanged. The system-suspend explanation is strongly supported, not directly confirmed by Windows power event logs.
- Phase 4 is complete. Phase 5 remains gated pending owner approval. See `deep_validation/11_phase4_results.md`.


## 2026-11-11 - Phase 5 failure analysis and self-healing

- Audited the existing classifier, self-healing agent, executor retry/healing decision, graph callers, and regression coverage. No production logic change was needed.
- Corrected the controlled end-to-end healing test setup: the saved learned test's text fallback previously bypassed locator failure, so the real seeded behavior defect correctly appeared without a healing attempt. The test now disables that fallback for the specific stale-selector case while retaining the expected-message assertion.
- Verification: focused classification/healing suite 141 passed, 8 slow tests deselected; DemoStore healing E2E 1 passed in 967.53s; Ruff passed. The selector repair was kept after rerun, and the seeded no-message defect remained `assertion_failure`.
- Phase 5 is complete. Phase 6 remains gated pending owner approval. See `deep_validation/12_phase5_results.md`.
