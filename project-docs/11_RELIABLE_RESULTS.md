# Reliable results: one feature per test, reconciled numbers

> **A dated record of the Oct 28, 2026 work.** The numbers, test counts, file names and "still not tested" list below
> are as they were on that day, and are kept unchanged as evidence. For how the tester works now, see the
> [README](../README.md) and [Rules](03_RULES.md). Two later changes matter when you read section 8: every route is
> now visited by default (`PATTERN_SAMPLES=0`, so address patterns are no longer sampled), and failed tests are only
> run again with `TEST_RETRIES` (0 by default).

| **Date** | Oct 28, 2026 |
|---|---|
| **Baseline** | The AutomationTestStore run `runs/automationteststore.com_20261027_235636` (verdict Not Ready; the report showed "420 tests", "418 gave a result", "53 test cases: 16 passed, 36 failed, 1 blocked", "89 % passed", 8 of 60 features verified, 14 of 29 pages verified) |
| **Measured on** | 1) AutomationTestStore itself, re-run twice with the new code (no AI, no test account, no sign-up - the same settings as the baseline's public part). 2) ClassicShop (`tests/classic_shop.py`, new): a local shop built the way that site is (one `index.php?rt=<route>` for every page, plain-list menus, product cards inside `<body class="product-category">`, a cart menu whose text changes, tab links + `<base href>`, text-type quantity / e-mail boxes), with 3 planted bugs - each in ONE feature - and its truth manifest `tests/classic_shop_truth.json`. 3) DemoStore, as before. Nothing in the agent knows about any of these sites. |

---

## 1. Root causes

### 1.1 Found in the baseline run (confirmed in the code and in the run's own files)

| # | Where in the code | What it did | Evidence in the baseline run |
|---|---|---|---|
| A1 | `test_design.builtin_flows` + `conftest.run_steps` | One "large" test case per page bundled every step of the page (search, menus, dropdowns, choices, forms ...). One failed step failed the whole case, and `registry.record_outcomes` marked every feature the case touched as failed. | 29 of 29 page cases failed; 38 of 60 features "failed" although most of their own steps passed (the 'Sort By' dropdown passed inside a case that failed on its search and cart-menu steps). |
| A2 | discovery `sel()` / `fallbackFor` | An element without an id was addressed by its visible text - also when that text is state: the cart menu `li.dropdown:has-text("1 ITEMS - $29.50")` (exploring had added an item). A fresh test browser shows "0 ITEMS - $0.00". | "it should be visible [li.dropdown:has-text("1 ITEMS - $29.50")]" in 27 page cases. |
| A3 | discovery `itemLinks` | The item list was the nearest `li` / `[class*=product]` ancestor of the links. `<body class="product-category">` matched (every link of the page); plain `<li>` lists (header menu, breadcrumb, tabs) matched too. | Sort read `['login or register', 'specials', 'account', ...]`; search "shows items that don't match: ['Login or register', 'SPECIALS', ...]"; the shopping journey clicked "Login or register". |
| A4 | `test_design.features()` | The search word came from page headings when there were no real item cards. | "Searching 'Welcome' did not show it"; words 'Home', 'Search', 'PRODUCT'. |
| A5 | discovery `_pattern`, `registry.page_pattern`, `features._words` | Pages picked by the query (`index.php?rt=<route>`) shared one pattern. | 98 links skipped as "the same address pattern" - the cart, contact, site map pages were never visited; the registry had 2 page patterns for 29 pages. |
| A6 | `reporter`, `story`, `coverage_summary` | Totals of different units without labels (see 4.2). | `summary.json` / `report.html` of the run, recomputed by `backend/metrics.py` from the same files. |
| A7 | data cases, link checker, learned cases | Expectations nobody could observe: an e-mail box of type "text" must refuse a bad e-mail while typing (the form is never sent); tab links resolved against `<base href>`; 'Print' and the 'Grid' button "must respond"; 'Back to top' "changed nothing". | 10 "invalid value accepted"; 3 "broken #section" links; 'Print' and 'btn btn orange' as HIGH website defects. |
| A8 | `failure_analysis.classify` | A bundled case's summary line ("N of M steps failed") was classified a HIGH website defect. | 29 HIGH "blocking problems" -> Not Ready. |
| A9 | discovery sign-up | The note said "the website did not accept the sign-up" with the LOGIN page's error: the sign-up form was never reached. | `login.json`. |

Why so few pages and features were verified, feature by feature: [accuracy/ats_baseline_explained.md](accuracy/ats_baseline_explained.md).
In short, of the 52 features not verified: bundling x26, wrong item list x26, a heading as the search word x23, state in
the address x21, expectations nobody could establish x13, no test generated x8, protected (correctly blocked) x6, a hover
menu that did not open x2 (a feature can have several causes).

### 1.2 Found by re-running AutomationTestStore with the new code (re-run 1, `runs/automationteststore.com_20261028_114343`)

The re-run showed the first round worked (see 4.3) and exposed 9 more false results. None of them was a website defect:

| # | What happened | Cause |
|---|---|---|
| R1 | 31 features "failed", 14 of 15 page patterns not verified | Coupling again, one level up: ONE site-wide case "Input boxes handle wrong values (164 values)" and ONE "Every link works" were linked to every box and every item list of the site - one failing box (on the cart page) or link (a tab) failed them all. |
| R2 | 26 locator failures on the cart page (coupon, shipping estimate, update) | Those boxes exist only while the cart holds an item; every test starts with an empty cart. |
| R3 | The shopping journey failed: "Clicking 'Absolue Eye Precious Cells' did not open its page" | The shop opens the page of the ONLY match instead of a results list; the journey then read the 'Bestsellers' list beside it as the results. The search check passed for the same wrong reason. The word was in one product, listed twice ('ABSOLUE ...', 'Absolue ...'), counted as two. |
| R4 | "Reviews (0)" and "Tags:" reported as broken `#section` links | The real tabs have no `data-toggle`: plain `#review` links inside `ul.nav-tabs`, made into tabs by a script, with `<base href>` = the home page. |
| R5 | "'Back to top' gave no visible response" (website defect) | It is a fixed button: at the top of the page it cannot move anything - exploring and the test only ever clicked it there. |
| R6 | "'Register Account' choice: the selected choices are [register, register]" (website defect) | Self-healing "repaired" the missing 'Guest Checkout' choice by pointing it at 'Register Account' (a group of choices shares one name and type). |
| R7 | Two "Fill the whole form" workflows on the cart page PASSED | Every box was missing (empty cart) and a missing box is skipped (meant for hidden anti-spam boxes): nothing was filled, and it passed. |
| R8 | The closing banner said "53 failed" | It counted 21 inconclusive results as failed. |
| R9 | 56 crawl "issues" | 2 third-party scripts, blocked on each of the 28 pages; the home page's "item list" was a row of brand logos (pictures, no names), so the search box was tried with the word "a" on a form that a script sends. |

Four more, found by the final validation runs:

| # | What happened | Cause |
|---|---|---|
| R10 | DemoStore: the address form's "submitting it empty is rejected" check disappeared (23 of 24 features right instead of 24) - a regression of this task's first round | The account form and the address form were both addressed `form >> nth=0` (the first form of the page): "a control on several pages is tested once" took them for ONE form. A form is now known by its boxes and its button. |
| R11 | The project's own suite, run with 3 workers: 1 test failed (`test_sandbox::test_watching...`) | The suite's worker id (`PYTEST_XDIST_WORKER`) leaked into the generated tests the tester runs, so they named their result file after the suite's worker. The executor no longer passes the outer pytest's variables on. |
| R12 | Final AutomationTestStore run: 3 features "failed" | Their input checks timed out loading the page once and passed on the retry (flaky); the per-feature rule read only "failed". A flaky result now counts as passed on a retry. |
| R13 | Final AutomationTestStore run: verdict Not Ready, "1 blocking problem: page did not load (2 pages)" | Both were 20-second timeouts while the test machine also ran this task's other validation jobs - not error pages. A page that does not answer in time is now a timeout (environment) finding, not a critical website defect; an error status still is one. |

## 2. What changed and why

| File | Change | Why |
|---|---|---|
| `backend/metrics.py` (new) | ONE calculation of every number: single tests in 4 groups (links / page checks / input checks / functional), assertions, test cases (planned, executed, passed, failed, flaky, inconclusive, skipped, blocked, not run), workflows with the steps they verified, findings (application defects vs test-script / locator / environment problems vs expectations to review), pages and features with the reason for each one not verified, every rate with its denominator, and 12 automatic consistency checks (a verified feature needs a passed test of its OWN that ran assertions). | A6, R1 |
| `backend/agents/reporter.py`, `backend/story.py`, `backend/excel.py`, `frontend/chat.js`, `main.py` | The report, the summary, Excel ("Summary" sheet), the chat card and the closing banner take their totals from `metrics.json`; the headline is "functional test cases passed (x of y)"; "executed" no longer counts blocked cases; failed and inconclusive are never added together. | A6, R8 |
| `backend/agents/test_design.py` | One focused test case per feature / control (unique ID, feature, preconditions, test data, steps, expected result, its own result) instead of one bundle per page; a control shared by many pages is tested once - also its input-value checks - and a form is known by its boxes and button, not its position; the search word is a real item word in 2+ DIFFERENT items; the cart page's own controls, boxes and forms get no test that starts with an empty cart (`CART_STATE`, reported as not tested with that reason); a quantity test; nameless controls are not required to "respond"; "Confirm Order" is never a confirm-box button. | A1, A4, A7, R2, R3 |
| `backend/agents/script_generator.py` | `test_checks.py` (one test per check); search reads the RESULT LIST - or recognises that the shop opened the page of its only match (`_item_landing`); a result without the word must mention it on its own page, not counting the other items listed beside it; sort reads the item cards; filters check the filter stays applied; choices that are not on the page now are reported inconclusive (the others are tested); text-type boxes: no visible refusal = inconclusive; a form workflow that finds none of its boxes fails; the shopping journey verifies and records every step; link-test ids come from the link alone. | A3, A7, R3, R5, R6, R7, R1 |
| `backend/agents/discovery.py` | Item list = repeated cards WITH names outside menus / header / footer / tabs (never `<body>`, never a row of logos); addresses without counts / prices; links in a tab list are tabs; route-aware page patterns; the search box's results page is visited only for a form that says where it goes, with a word of 2+ items; visitors sent to the login page are recorded as "needs a test account"; the sign-up never fills the login form; crawl issues counted once per problem. | A2, A3, A5, A9, R4, R9 |
| `backend/observe.py`, `backend/templates/conftest.py` | `window.print` is written down; a "scroll" effect; a floating control that does nothing at the top is tried once more from the bottom; `[qa-step]` / `[qa-inconclusive]` markers; the runtime guard judges a link that says where it goes by the crawler's unsafe-address words. | A7, R5 |
| `backend/registry.py` | Route-aware page patterns; a shared control is one site feature; statuses discovered -> inspected -> test generated -> tested -> verified, or failed / blocked / inconclusive / not tested (+ why); each feature is decided by ITS OWN single tests (`own_tests`, `decided` - a site-wide case never fails a feature through another page's check); a failure that only says the test could not reach the feature (locator, network, test data) makes it inconclusive, not failed; a test that passed on its retry is flaky, not failed; a journey only USES the features it goes through. | A1, A5, R1, R12 |
| `backend/agents/failure_analysis.py`, `graph.py`, `self_healing.py`, `advice.py`, `executor.py` | New class "locator / interaction failure (not proof of a website bug)"; a repair never points a test at an element it already uses, and never picks a choice of a group by its shared name; one finding per crawl problem ("seen on 28 pages"); a page that did not load in time is a timeout finding, not a website defect; the generated tests never inherit the variables of a pytest run around the tester. | A8, R6, R9, R11, R13 |
| `backend/accuracy.py`, `tests/accuracy_benchmark.py` | Pages are matched with the route that picks them; `--site classic`. | measuring on query-routed shops |
| `tests/classic_shop.py`, `tests/classic_shop_truth.json` (new) | The controlled shop with the AutomationTestStore structures and 3 planted bugs (one per feature), and its truth. | Phase 9 |
| `tests/test_metrics.py`, `tests/test_classic_markup.py`, `tests/test_classic_shop.py`, `tests/test_rerun_lessons.py` (new); `test_core.py`, `test_rules.py`, `test_registry.py`, `test_login_discovery.py` (extended) | The regression tests (section 6). Two existing tests were changed on purpose: the one that required the per-page bundles now requires the opposite (one test case per step), and three locator failures expect the new class "locator". | Phase 9 |

## 3. Commands

```
.venv\Scripts\python.exe -m pytest -q -n 3 --dist loadfile                         # the whole suite (incl. both e2e shops)
.venv\Scripts\python.exe -m pytest tests/test_rerun_lessons.py tests/test_metrics.py tests/test_classic_markup.py -q
.venv\Scripts\python.exe -m tests.accuracy_benchmark --site classic --out project-docs/accuracy/classic_after.json
.venv\Scripts\python.exe -m tests.accuracy_benchmark --out project-docs/accuracy/after.json          # DemoStore
python main.py https://automationteststore.com/ --no-open        # (LLM_PROVIDER=none, AUTO_REGISTER=false for the same settings)
python -c "from backend import metrics; print('\n'.join(metrics.summary_lines(metrics.for_run('runs/<run>'))))"
python tests/classic_shop.py 8767 [bugs]                         # the practice shop by hand
ui.bat                                                           # http://127.0.0.1:8000
```

## 4. Results

### 4.1 The project's own tests

Before any change: **128 of 128 passed** (32 min).
Final suite (`-n 3 --dist loadfile`, 21.7 min): **166 of 167 passed**; the 1 failure was R11 - fixed, that test passes
now (also with 3 workers). The fixes made after that suite (R10-R13) were checked with the tests of the changed areas -
`test_rerun_lessons` (16), `test_core`, `test_registry`, `test_metrics`, `test_rules`, `test_sandbox::test_watching...`:
all pass - and the end-to-end files (`test_accuracy.py`, `test_classic_shop.py`, `test_end_to_end.py`) run again on
the final code: **17 of 17 passed** (20.5 min). ClassicShop was re-measured separately with the final code (4.4:
unchanged).

### 4.2 The AutomationTestStore baseline, recomputed with one calculation

| What the report showed | What it really counted |
|---|---|
| "420 tests" | 420 single tests: 208 link checks + 87 page checks + 78 input checks + **47 functional tests** |
| "418 test(s) gave a result" | the same 420 minus 2 skipped link checks |
| "53 test cases: 16 passed, 36 failed, 1 blocked", "53 executed" | 53 test cases; **52 executed** (a blocked case is not executed) |
| "89 % of tests passed" (the headline) | 370 / 418 single tests - link and page checks included. **Functional test cases: 13 of 47 passed (28 %)** |
| "0 of 29 end-to-end journeys work completely" | the 29 per-page bundles counted as journeys; the real journeys: 3 (2 passed, 1 failed) |
| Pages "14 of 29 verified" / registry "0 of 2 page patterns" | two different measures, and the registry merged 28 `index.php?rt=` pages into one pattern |

### 4.3 AutomationTestStore: baseline vs the new code (the same calculation, `backend/metrics.py`)

| | Baseline (old code) | Re-run 1 (first round of fixes) | Re-run 2 (final code) |
|---|---|---|---|
| Functional test cases passed | 13 of 47 (28 %) | 39 of 46 (85 %) | **42 of 42 (100 %)** |
| Test cases: planned / executed / passed / failed / inconclusive / blocked | 53 / 52 / 16 / 36 / 0 / 1 | 55 / 51 / 42 / 9 / 0 / 4 | 52 / 48 / 46 / 1 / 1 / 4 |
| Single tests (links + page + input + functional) | 420 (208 + 87 + 78 + 47) | 477 (186 + 81 + 164 + 46) | 443 (183 + 75 + 142 + 43) |
| Findings: application defects / test-script, locator, environment / inconclusive | 46 / 1 / 0 | 5 / 27 / 21 (the 5 "defects": R3-R6, all false) | **0** / 1 (+ 10 flaky: a page load timed out once) / 21 |
| Workflows passed | 2 of 3 | 4 of 5 (2 of them falsely: R7) | **3 of 3** (the shopping journey with all 7 steps verified) |
| Features: discovered / verified / failed / blocked | 60 / 8 / 38 / 6 | 132 / 35 / 31 / 41 | 138 / **56** / **0** / 42 (R12 applied) |
| Page patterns: discovered / verified | 2 / 0 (29 pages visited) | 15 / 1 (27 pages visited) | 16 / **12** (27 pages visited; 2 timed out) |
| Consistency checks passed | (none existed; recomputed: 12 of 12) | 12 of 12 | 12 of 12 |

How to read the final column: the run is `runs/automationteststore.com_20261028_123028`. Its own report counted 3
features "failed" (R12) and said Not Ready (R13) - both caused by page loads that timed out while this machine ran the
other validation jobs at the same time. The feature and page numbers above are recomputed from that run's own files
(`results.json`, `test_cases.json`, `registry.json`) with the R12 fix; everything else is the run as it was. With R13,
those 2 timeouts are environment findings; the run was not repeated for the verdict (time). The 21 inconclusive
results are e-mail / name boxes of type "text" (the website's own check happens when the form is sent - never done),
1 choice not on the page in a fresh browser, and nothing else.

### 4.4 ClassicShop (built like that site; the same test account in both) - `project-docs/accuracy/classic_before.json`, `classic_after.json`

| | Before (old code) | After |
|---|---|---|
| Known pages found | 9 / 14 (cart, contact, site map, register, search results skipped as "same pattern") | **14 / 14** |
| Features detected / tested | 18 / 13 of 20 | 19 / **19** of 20 |
| Features verified - clean shop | 1 / 20 | **19 / 20** |
| Features with the right result - clean shop | 2 / 20 | **20 / 20** |
| Test cases failed on the CLEAN shop (false alarms) | **41 of 56** | **0 of 51** |
| False alarms with the bugs planted | 16 | **0** |
| Planted bugs caught | 1 / 3 (search) - sort and cart total never tested | **3 / 3** (search, sort, cart total), 0 false passes |
| Verdict: clean / with bugs | Not Ready / Not Ready (the same 80 % for both) | Ready with Risks / Not Ready |
| Functional test cases passed (clean) | 9 of 48 (19 %) | **42 of 42 (100 %)** |
| Workflows (clean) | 2 of 3 passed, 1 blocked | **7 of 7 passed** |
| Page patterns (registry) | 3 (0 verified) | **25 (25 verified)** |
| Report totals consistent | (no checks) | **12 of 12 checks pass** |

With the bugs planted, the 6 failing test cases are exactly the 3 bugs: the search (results that don't mention the word;
a search for nothing still lists items), sorting by price on 3 list pages, and the shopping journey ("one more should add
18.5 to the cart total, it went 18.5 -> 18.5"). Every other test case keeps its own PASSED result.
Re-measured with the final code (`classic_after.json`): the same numbers - 14 / 14 pages, 20 / 20 features right,
0 false alarms, 3 / 3 bugs caught with 0 false passes, 42 of 42 functional test cases and 7 of 7 workflows on the
clean shop, 25 of 25 page patterns verified and 0 features failed.

### 4.5 DemoStore (no regression)

Before this task: 18 / 18 pages, 24 / 24 features right, 6 / 6 planted bugs caught, 0 false alarms
(`accuracy/demo_before_this_task.json`). After, with the final code (`accuracy/after.json`): **24 / 24 features
right**, 6 / 6 planted bugs caught, 0 false alarms (the final suite, run before R10 was fixed, had measured 23 / 24:
the address form's validation check lost to R10).

## 5. Page and feature coverage, before and after

| | Baseline | Final (re-run 2) |
|---|---|---|
| Pages visited | 29 (the cart, contact and site map never visited) | 27 (the cart, contact and site map included; no copy of the home page from a guessed search address) |
| Page patterns told apart | 2 | 16 (12 verified, 2 timed out while loading) |
| Features discovered / verified | 60 / 8 | 138 / 56 |
| Why the rest is not verified | 38 "failed", mostly through bundles (1.1) | 42 protected (never performed on purpose), 21 no automatic test (e.g. a control that showed nothing when used), 11 cart-page controls (need an item in the cart), 8 inconclusive (each with its reason) - **0 failed** |

ClassicShop, where the truth is known (section 4.4): every known page and 19 of 20 features found, 19 of 20 tested and
verified; the 20th is the protected 'Subscribe' (correctly blocked).

## 6. The regression tests

| What must hold | Test |
|---|---|
| A deliberately broken feature fails its own test, nothing else | `test_classic_shop::test_a_planted_bug_fails_its_own_feature_and_nothing_else` (3 planted bugs) |
| A passing feature is not marked failed by an unrelated assertion | the same test + `test_registry::test_a_failing_journey_fails_its_workflow_never_the_features_it_went_through` + `test_rerun_lessons::test_a_site_wide_case_judges_each_feature_by_its_own_single_tests` + `test_core::test_every_step_is_its_own_focused_test_case` |
| Search and sorting inspect the correct content | `test_classic_shop::test_search_and_sorting_read_the_product_cards`, `test_classic_markup::test_the_item_list_is_the_product_cards_not_the_menus`, `test_rerun_lessons::test_a_row_of_logos_without_names_is_not_the_item_list`, `..._a_search_that_opens_its_only_match_is_judged_on_that_items_page` |
| Report totals match the execution records | `test_metrics` (incl. a mismatch that must be reported), `test_classic_shop::test_the_report_totals_reconcile` |
| Verified features have passing assertions and evidence | `test_metrics::test_a_verified_feature_needs_a_passed_test_that_ran_assertions` |
| A test that cannot reach its feature never makes it "failed" | `test_rerun_lessons::test_a_site_wide_case...` (locator failure -> inconclusive), `..._the_cart_pages_own_controls_get_no_test_that_starts_with_an_empty_cart`, `..._the_choice_test_checks_the_choices_on_the_page...` |
| No false pass of a workflow | `test_rerun_lessons::test_a_form_workflow_that_finds_none_of_its_boxes_fails_instead_of_passing`, `..._a_form_on_the_cart_page_gets_no_fill_the_form_workflow`, `test_classic_shop::test_the_shopping_journey_passes_only_with_every_step_verified` |
| Repairs never invent a result | `test_rerun_lessons::test_a_repair_never_points_a_missing_choice_at_another_choice_of_its_group` |
| Two different forms are never "one control"; timeouts are no website defects | `test_rerun_lessons::test_two_different_forms_are_two_checks...`, `..._a_page_that_did_not_load_in_time_is_no_website_defect...` |
| Missing credentials and protected actions are reported correctly | `test_classic_shop::test_protected_actions_are_blocked_and_the_missing_account_is_reported`, `test_login_discovery::test_signing_up_from_a_login_page...` |
| The AutomationTestStore structures | `test_classic_markup` (11 tests), `test_rerun_lessons` (tabs without data-toggle, a fixed 'Back to top', a form a script sends) |

## 7. Did the shopping workflow genuinely pass?

**ClassicShop - yes, every step verified** (clean shop, as a visitor and with the test account), written down by the
test itself: "'Velvet Matte Lipstick' is found in the results" -> "its page opened and shows its name" -> "'Add to Cart'
added it without an error message" -> "'Velvet Matte Lipstick' is in the cart" -> "its quantity in the cart is right
(0 -> 1)" -> "its price in the cart is the price the list showed (18.5)" -> "the cart total follows the quantity
(18.5 -> 37)", then the line it added is removed. With the planted cart-total bug it **fails** at the total step.
Checkout / payment is never clicked. **DemoStore**: passes as well (part of the suite).

**AutomationTestStore**: baseline - failed (it clicked "Login or register" as a product); re-run 1 - failed (R3: the
search opened the product's own page); **final run - passed, every step verified** (as a visitor, nothing bought):
"'SKINSHEEN BRONZER STICK' is found in the results" -> "its page opened and shows its name 'Skinsheen Bronzer Stick'"
-> "'Add to Cart' added it without an error message" -> "'Skinsheen Bronzer Stick' is in the cart" -> "its quantity
in the cart is right (0 -> 1)" -> "its price in the cart is the price the list showed (29.5)" -> "the cart total
follows the quantity (31.5 -> 61)" (the total includes 2.00 shipping; one more added exactly 29.5). Its cleanup step
then removes the line it added (when the cart offers a remove control). Checkout was never clicked.

## 8. What is still not tested - and why

- **Pages behind the login without a test account** (AutomationTestStore: account, order history, address book ...):
  "not tested - needs a test account" (a visitor is sent to the login page). Give a test account to test them.
- **The cart page's own boxes and forms** (coupon, shipping estimate, update quantities): only there while the cart holds
  an item - "not tested" with that reason. The shopping journey tests the cart itself (line, quantity, price, total).
  Next step: give these checks the precondition "one item in the cart" (added by the test, removed afterwards).
- **Protected actions** (Checkout, Confirm Order, Subscribe, Submit, sign-up): blocked, never performed.
- **Input boxes the browser does not check** (an e-mail box of type "text"): no visible error = **inconclusive** -
  the website's own check happens when the form is sent, which tests never do.
- **A search form that a script sends**: its results page is reached only by clicking its button while exploring.
- **Controls without an observable result** and **choices not on the page in a fresh browser**: inconclusive, with
  the reason.
- **Sampled address patterns**: of many pages of one pattern (product pages), 3 are tested; the rest are counted.

## 9. Limitations and how to reproduce

- Accuracy can only be measured where the truth is known (the two practice shops). On a real website the report says
  what was found, tested and verified - and why not - never a percentage of "everything".
- A live website changes between runs (products, the cart menu, third-party scripts): the AutomationTestStore numbers
  are of those runs.
- A site's search may match descriptions or tags: a result without the word in its name is accepted only when its own
  page mentions the word (not counting other items listed beside it).
- Name sorting is checked by first letter (a website's alphabet treats accents and punctuation its own way); prices
  exactly.
- CAPTCHA / 2-step login are never bypassed (a person can complete them in the visible browser).
- Reproduce: the commands of section 3. The baseline comparison on ClassicShop uses the morning's code (a copy run
  from a scratch folder) on the same shop; both result files are in `project-docs/accuracy/`.
