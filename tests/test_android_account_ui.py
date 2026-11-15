"""Account policy is explicit and shared by Standard and MCP Android setup."""

import pytest
from playwright.sync_api import expect

from tests import test_qpilot_ui

ui = test_qpilot_ui.ui


@pytest.mark.parametrize("mcp", [False, True])
def test_account_choices_use_one_set_of_fields_without_storing_credentials(ui, mcp):
    page, requests, errors = ui
    page.locator("#mobileModeBtn").click()
    if mcp:
        page.locator("#mcpWorkflowBtn").click()
    mode = page.locator("#androidAccountMode")
    expect(mode).to_be_visible()
    expect(mode).to_have_value("none")
    expect(page.locator("#androidAccountCredentials")).to_be_hidden()
    mode.select_option("existing")
    expect(page.locator("#androidAccountCredentials")).to_be_visible()
    page.locator("#androidTestUsername").fill("private-fixture-user")
    page.locator("#androidTestPassword").fill("private-fixture-password")
    body = page.evaluate("Object.fromEntries(QpilotChat.androidRequest(false))")
    assert body["account_mode"] == "existing" and body["test_username"] == "private-fixture-user"
    assert body["test_password"] == "private-fixture-password"
    mode.select_option("create")
    expect(page.locator("#androidTestPassword")).to_have_value("")
    expect(page.locator("#androidAccountHelp")).to_contain_text("one new account")
    page.evaluate("document.getElementById('androidTestBuild').checked = true")
    body = page.evaluate("Object.fromEntries(QpilotChat.androidRequest(false))")
    assert body["account_mode"] == "create"
    assert "test_username" not in body and "test_password" not in body
    storage = page.evaluate("JSON.stringify({...localStorage,...sessionStorage})")
    assert "private-fixture" not in storage
    assert page.locator("#androidTestUsername").count() == 1
    assert not requests and not errors


def test_stale_backend_cannot_silently_drop_account_policy_or_start_a_test(ui):
    page, requests, errors = ui
    environment = {"ok": True, "execution_revision": 3,
                   "devices": [{"device_id": "emulator-5554", "status": "device"}]}
    page.route("**/api/android/environment?*", lambda route: route.fulfill(json=environment))
    page.locator("#mobileModeBtn").click()
    page.locator("#androidMode").select_option("installed")
    page.locator("#androidPackage").fill("com.example.fixture")
    page.locator("#androidDevice").select_option("emulator-5554")
    page.locator("#androidAuthorized").check()
    page.locator("#androidTestBuild").check()
    page.locator("#androidAccountMode").select_option("create")
    expect(page.locator("#androidStart")).to_be_enabled()
    environment["execution_revision"] = 2
    page.locator("#androidStart").click()
    expect(page.locator("#androidRunNote")).to_contain_text("restart ui.bat")
    assert not requests and not errors


def test_mcp_preparation_rejects_stale_backend_before_storing_private_settings(ui):
    page, requests, errors = ui
    page.route("**/api/android/environment?*", lambda route: route.fulfill(json={"execution_revision": 2}))
    page.locator("#mobileModeBtn").click()
    page.locator("#mcpWorkflowBtn").click()
    result = page.evaluate("""async () => {
      try { await QpilotMcpSettings.prepare('android','com.example.fixture','Verify login'); return ''; }
      catch (error) { return error.message; }
    }""")
    assert "restart ui.bat" in result
    assert not requests and not errors
