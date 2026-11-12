# 01 — Workflow discovery validation

**Status: PARTIALLY VERIFIED · score: 5/10**  
**Scope:** Local test sources, historical run evidence, and one current non-slow suite attempt. No external target was tested.

## Evidence

- Source: `backend/agents/discovery.py`, `backend/observe.py`, `backend/page_inventory.py`, `backend/agents/test_design.py`, `backend/agents/script_generator.py`, `backend/agents/executor.py`, `backend/agents/reporter.py`.
- Relevant local regression suites: `tests/test_deep_exploration.py`, `tests/test_like_a_user.py`, `tests/test_login_discovery.py`, `tests/test_page_inventory.py`, `tests/test_modal_form_accuracy.py`, `tests/test_forms_and_writes.py`, `tests/test_rules_between_fields.py`, `tests/test_stay_in_section.py`, `tests/test_android_site.py`, `tests/test_android_site_dialog_forms.py`, `tests/test_android_app.py`, `tests/test_android_protocol.py`.
- Historical local web contract run: `logs/appium-web-regression.xml` records 1 test, 0 failures/errors, 46.154 seconds (2026-11-08). It tests the web submission pipeline against a controlled local fixture with planted defects; the test asserts the report identifies the defects and returns `Not Ready`.
- Historical Android/device suite: `logs/appium-final-regression.xml` records 176 cases, 0 failures, 0 errors, 1 skipped, 115.947 seconds (2026-11-08). This is a focused Android regression, not a full product suite or proof of whole-app coverage.
- Current run: `deep_validation/pytest-nonslow.txt` records 406 passed, 21 failed, 324 errors in 26.88 seconds. Numerous failures/errors show `PermissionError [WinError 5]` creating pytest temp directories or launching Playwright subprocesses. Treat the run as **environment-blocked/inconclusive**, not as a clean pass or a reliable count of product defects.

## Workflow coverage matrix

| Workflow / behavior | Existing coverage/evidence | Current conclusion |
|---|---|---|
| Multi-page navigation and page inventory | Discovery, route/scope, nested opener, and page inventory tests exist. Historical focused suites include related web and Android path behavior. Current broad run hit temp/subprocess permission errors. | Partial; no fresh complete workflow run. |
| Login and session persistence | `tests/test_login_discovery.py`, `tests/test_deep_exploration.py`, `tests/test_android_site.py`; controlled Android run on 2026-11-08 includes login checks. | Partial; fixtures and historical evidence exist; not rerun successfully now. |
| Registration then login/logout | `tests/test_android_site.py` and `tests/test_android_site_dialog_forms.py`; historical clean controlled app run includes registration/login scenarios. | Partial; fresh browser-based fixture run blocked. |
| Search, filtering, pagination, cart and cross-page state | `tests/test_android_site.py`, `tests/test_android_site_dialog_forms.py`, `tests/test_cart_and_search_lessons.py`, `tests/test_deep_exploration.py`. | Partial; individual test coverage exists, but current run did not produce reliable execution evidence. |
| Checkout / mock payment | Protected-action rules explicitly block checkout/payment by default (`backend/actions.py`, `backend/qa_contracts.py`, Android tests asserting checkout is not pressed). | Not verified as a successful mock-payment journey; safety behavior is verified in historical unit coverage, not payment completion. |
| Form submission and multi-step forms | `tests/test_forms_and_writes.py`, `tests/test_rules_between_fields.py`, `tests/test_like_a_user.py`, `tests/test_modal_form_accuracy.py`; controlled QA contracts cover forms. | Partial; staging/approved flow is possible, but not every target’s semantics are inferable. |
| Roles and access restrictions | `tests/test_extensions.py`, `tests/test_roles` coverage through role-related fixtures; `backend/roles.py`. | Partial; source and historical suite coverage, no fresh successful end-to-end run. |
| Dynamic content, dialogs/modals | `tests/test_busy_server_lessons.py`, `tests/test_modal_form_accuracy.py`, `tests/test_android_site_dialog_forms.py`. | Partial; relevant scenarios exist but current test execution is blocked. |
| Back/forward navigation | Browser/Android navigation helpers and Android interaction tests exist; no dedicated successful current run was captured in this validation. | Unverified for this audit. |
| Unvisited or bounded states | Reports record page/control limits, blocked items and omitted cases (`backend/registry.py`, `backend/metrics.py`, `backend/android_reporting.py`). | Source-supported; fresh end-to-end report not regenerated here. |

## Execution details

**Scenario:** run local fixture/regression tests without touching external sites.  
**Expected:** local workflow tests execute; reports distinguish completed, blocked and unvisited states.  
**Actual:** the full non-slow test command began but failed broadly under access-denied temp and subprocess restrictions. Historical XML evidence is available but predates this run.  
**Pass/fail:** current validation inconclusive; not a product pass.  
**Confidence:** medium for existence of workflow mechanisms; low for current end-to-end reliability.  
**Limitation:** broad claims such as “all workflows” require app-specific expected outcomes and states. The product itself imposes page, depth, action, time and case caps.

## Next action

Rerun the local fixture suite from an execution environment where pytest can create and enumerate its temporary directories and Playwright can launch subprocesses. Keep checkout/payment blocked unless the fixture explicitly uses an inert mock payment and the relevant safety approval is configured.
