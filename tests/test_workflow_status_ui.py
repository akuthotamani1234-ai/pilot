"""The Jira workspace in a real browser (real Studio server, mock Atlassian): connection and workflow indicators show
only what the backend verified - nothing green on first opening, 'Unable to verify' when the Studio does not answer,
red for refused credentials, green for Connect Jira only after Atlassian answered (and nothing else with it), and a
change made elsewhere (a disconnected site) reaches the page by itself."""
import re

import httpx
from playwright.sync_api import expect

from tests.atlassian_mock import EMAIL, TOKEN
from tests.test_requirements_ui import browser, open_page, studio  # noqa: F401


def _stage(page, name):
    return page.locator("#wfList li", has_text=name).first


def test_indicators_follow_verified_state_only(browser, studio):  # noqa: F811
    ctx, page, errors = open_page(browser, studio)
    try:
        expect(page.locator("#ovConnSummary")).to_contain_text("Jira: Not connected")
        expect(page.locator("#ovConnSummary")).to_contain_text("Confluence: Not connected")
        assert page.locator(".rq-nav a.done").count() == 0
        page.route("**/api/requirements/connections/status*", lambda r: r.abort())
        page.reload()
        expect(page.locator("#ovConnSummary")).to_contain_text("Jira: Unable to verify")
        page.unroute("**/api/requirements/connections/status*")
        page.goto(studio.url + "/requirements#integrations")
        page.fill("#jiraSite", "https://example-qpilot.atlassian.net")
        page.fill("#jiraEmail", EMAIL)
        page.fill("#jiraToken", "WRONG-TOKEN-1234567")
        page.get_by_role("button", name="Connect").first.click()
        expect(page.locator('.rq-conn[data-conn="jira-main"] h3')).to_contain_text("Connection failed")
        page.goto(studio.url + "/requirements#import")
        expect(_stage(page, "Connect Jira")).to_have_attribute("data-status", "failed")
        expect(_stage(page, "Import")).to_have_attribute("data-status", "blocked")
        page.goto(studio.url + "/requirements#integrations")
        page.fill("#jiraToken", TOKEN)
        page.get_by_role("button", name="Save changes").first.click()
        expect(page.locator('.rq-conn[data-conn="jira-main"] [role=status]')).to_contain_text("Connected as")
        expect(page.locator('.rq-conn[data-conn="jira-main"] h3')).to_contain_text("Connected")
        page.goto(studio.url + "/requirements#import")
        expect(_stage(page, "Connect Jira")).to_have_attribute("data-status", "done")
        assert page.locator("#wfList li[data-status=done]").count() == 1  # (nothing else turned green)
        expect(page.locator('.rq-nav a[data-view="integrations"]')).to_have_class(re.compile(r"\bdone\b"))
        # a change made elsewhere (another tab / the API): the page follows by itself, without navigating
        httpx.delete(studio.url + "/api/requirements/connections/jira-main/token", headers={"X-Agentic-QA": "1"})
        expect(_stage(page, "Connect Jira")).to_have_attribute("data-status", "pending", timeout=15000)
        expected = ("net::ERR_FAILED", "status of 424")  # (the aborted status call and the refused token, on purpose)
        assert not [e for e in errors if "favicon" not in e and not any(x in e for x in expected)]
    finally:
        ctx.close()
