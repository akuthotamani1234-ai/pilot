"""Guided, approved expected-result configuration without running automation."""
import json

import pytest
from fastapi import HTTPException
from playwright.sync_api import expect

from backend.server import validate_qa_contract
from tests.test_results_layout import browser as shared_browser, studio


@pytest.fixture(scope="module")
def browser():
    yield from shared_browser.__wrapped__()


def test_accessibility_skip_link_is_focused_before_journey_click(browser):
    import re

    from backend.agents.script_generator import JOURNEY_HELPERS

    scope = {"re": re}
    exec(JOURNEY_HELPERS, scope)
    page = browser.new_page()
    try:
        page.set_content('''<style>.skip{position:absolute;top:-100px}.skip:focus{top:0}</style>
            <a class="skip" href="#content">Skip to content</a><main id="content" style="margin-top:1000px">Main</main>''')
        link = scope["_link"](page, {"text": "Skip to content", "href": "#content", "section": "content"})
        link.click(timeout=1000)
        assert page.url.endswith("#content")
        expect(page.locator("#content")).to_be_in_viewport()
    finally:
        page.close()


def test_browser_contract_waits_for_a_delayed_control(browser):
    from backend.qa_contracts import Locator, parse_contract
    from backend.qa_web import BrowserContractAdapter

    page = browser.new_page()
    page.route("https://example.test/**", lambda route: route.fulfill(content_type="text/html", body='''
        <script>setTimeout(()=>document.body.innerHTML='<button id="ready">Ready</button>',250)</script>'''))
    try:
        page.goto("https://example.test/")
        adapter = BrowserContractAdapter(page, page.url, parse_contract())
        assert adapter.find(Locator(strategy="css", value="#ready")).inner_text() == "Ready"
    finally:
        page.close()


@pytest.mark.parametrize("width,height", [(1024, 529), (390, 844)])
def test_guided_flow_validates_expected_results_and_keeps_mobile_controls_accessible(browser, width, height):
    context, page, errors, calls = studio(browser, viewport={"width": width, "height": height})
    submitted = []

    def validate(route):
        payload = route.request.post_data_json
        submitted.append(payload)
        try:
            route.fulfill(json=validate_qa_contract(payload))
        except HTTPException as e:
            route.fulfill(status=e.status_code, json={"detail": e.detail})

    page.route("**/api/contracts/validate", validate)
    try:
        page.locator("#mobileModeBtn").click()
        page.locator("#androidMode").select_option("web")
        expect(page.locator("#androidUrl")).to_be_visible()
        assert page.locator("#androidUrl").get_attribute("required") is not None
        expect(page.locator("#androidApk")).to_be_hidden()
        expect(page.locator("#androidPackage")).to_be_hidden()
        page.locator(".mobile-advanced > summary").click()
        page.locator('[data-flow-tools="androidContract"] .flow-open').click()
        expect(page.locator("dialog")).to_be_visible()
        page.locator("#flowName").fill("Required username")
        row = page.locator(".flow-step").first
        row.locator(".flow-action").select_option("fill")
        row.locator(".flow-locator").fill("#username")
        row.locator(".flow-value").fill("demo")
        page.locator("#flowApproved").check()
        page.locator("#flowEnvironment").check()
        page.locator('#flowForm [type="submit"]').click()
        expect(page.locator("#flowMessage")).to_contain_text("Invalid test flow")
        expect(page.locator("dialog")).to_be_visible()
        assert page.locator("#androidContract").input_value() == ""
        page.locator("#flowAdd").click()
        row = page.locator(".flow-step").last
        row.locator(".flow-action").select_option("assert_text")
        row.locator(".flow-locator").fill("#heading")
        row.locator(".flow-value").fill("Dashboard")
        page.locator('#flowForm [type="submit"]').click()
        expect(page.locator("dialog")).not_to_be_visible()
        contract = json.loads(page.locator("#androidContract").input_value())
        assert contract["test_environment"] and contract["flows"][0]["approved"]
        assert contract["flows"][0]["steps"][1]["value"] == "Dashboard"
        assert submitted and not errors
        assert "/api/mobile/runs" not in calls
    finally:
        context.close()


@pytest.mark.parametrize('width,height', [(1024, 529), (390, 844)])
def test_native_flow_builder_exposes_permission_and_gesture_fields_without_running(browser, width, height):
    context, page, errors, calls = studio(browser, viewport={'width': width, 'height': height})

    def validate(route):
        try:
            route.fulfill(json=validate_qa_contract(route.request.post_data_json))
        except HTTPException as error:
            route.fulfill(status=error.status_code, json={'detail': error.detail})

    page.route('**/api/contracts/validate', validate)
    try:
        page.locator('#mobileModeBtn').click()
        page.locator('.mobile-advanced > summary').click()
        page.locator('[data-flow-tools="androidContract"] .flow-open').click()
        page.locator('#flowName').fill('Approved emulator permission expectation')
        page.locator('#flowTimeout').fill('180')
        row = page.locator('.flow-step').first
        row.locator('.flow-action').select_option('permission_state')
        expect(row.locator('.flow-locator')).to_be_hidden()
        row.locator('.flow-value').fill('denied')
        page.locator('#flowAdd').click()
        row = page.locator('.flow-step').last
        row.locator('.flow-action').select_option('scroll_to')
        row.locator('.flow-locator').fill('Home-screen')
        row.locator('.flow-target').fill('Footer')
        row.locator('.flow-value').fill('up')
        page.locator('#flowAdd').click()
        row = page.locator('.flow-step').last
        row.locator('.flow-action').select_option('assert_permission')
        row.locator('.flow-value').fill('denied')
        page.locator('#flowPermissionApp').fill('Fixture App')
        page.locator('#flowPermissionApproved').check()
        page.locator('#flowApproved').check()
        page.locator('#flowEnvironment').check()
        page.locator('#flowForm [type="submit"]').click()
        expect(page.locator('dialog')).not_to_be_visible()
        contract = json.loads(page.locator('#androidContract').input_value())
        assert contract['android_permissions']['approved']
        assert contract['flows'][0]['steps'][1]['target']['value'] == 'Footer'
        assert contract['flows'][0]['timeout_s'] == 180
        assert '/api/mobile/runs' not in calls and not errors
    finally:
        context.close()


@pytest.mark.parametrize('width,height', [(1024, 529), (390, 844)])
def test_example_picker_preserves_existing_flows_and_keeps_permission_tests_unapproved(browser, width, height):
    from backend.server import contract_example, contract_examples

    context, page, errors, calls = studio(browser, viewport={'width': width, 'height': height})
    page.route('**/api/contracts/examples', lambda route: route.fulfill(json=contract_examples()))
    page.route('**/api/contracts/examples/*', lambda route: route.fulfill(
        json=contract_example(route.request.url.rsplit('/', 1)[-1])))
    try:
        # The picker may already have loaded before the new intercepts were registered.
        page.reload(wait_until='networkidle')
        page.locator('#mobileModeBtn').click()
        page.locator('.mobile-advanced > summary').click()
        page.locator('.android-raw-contract > summary').click()  # the JSON box is in its own collapsed section
        tools = page.locator('[data-flow-tools="androidContract"]')
        original = '{"version":1,"flows":[]}'
        page.locator('#androidContract').fill(original)
        tools.locator('.flow-example').select_option('wdio-complete')
        tools.locator('.flow-load-example').click()
        expect(page.locator('#androidContract')).not_to_have_value(original)
        contract = json.loads(page.locator('#androidContract').input_value())
        assert len(contract['flows']) == 33
        assert not contract['android_permissions'].get('approved', False)
        assert sum(not flow.get('approved', False) for flow in contract['flows']) == 7
        expect(page.locator('#androidPermissionApproval')).not_to_be_checked()
        expect(page.locator('#androidPermissionPolicy')).to_be_visible()
        tools.locator('.flow-undo-example').click()
        expect(page.locator('#androidContract')).to_have_value(original)
        expect(page.locator('#androidPermissionPolicy')).to_be_hidden()
        page.locator('#androidMode').select_option('web')
        expect(tools.locator('.flow-example option[value="wdio-complete"]')).to_have_count(0)
        expect(tools.locator('.flow-example option[value="chrome-dropdown"]')).to_have_count(1)
        assert '/api/mobile/runs' not in calls and not errors
    finally:
        context.close()
