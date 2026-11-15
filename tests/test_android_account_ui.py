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
