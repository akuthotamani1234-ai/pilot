"""Root cause of the load-sensitive Jira UI failure (26 Nov full suite: the Explorer showed every row after it was
filtered to one): a real race, not slowness. A view loaded again while its previous request was still answering, and
the OLDER answer, arriving last, overwrote the newer one. A busy server reorders answers; a slow network would do the
same to a person. The first test makes the older answer arrive last on purpose (independent of machine load): it
FAILED on the code before the fix (3 rows instead of 1) and passes with it (frontend/requirements.js newest()).
The second test guards the same fix on the connection cards ('token saved' once missed under load); its stale answer
could not be made to overwrite the cards deterministically, so it is a regression guard, not a reproduction."""
from playwright.sync_api import expect

from backend import requirements_api as rapi
from tests.atlassian_mock import EMAIL, TOKEN
from tests.test_requirements_ui import browser, open_page, studio  # noqa: F401

def slow_nth(page, match: str, nth: int) -> None:
    """From the next page load on, the answer of the nth GET whose address contains `match` (sent at once, so it
    holds the data of that moment) reaches the page 1.5 s late."""
    page.context.add_init_script("(" + SLOW_OLDER + ")(" + __import__("json").dumps([match, nth]) + ")")
    page.goto("about:blank")


SLOW_OLDER = """([match, nth]) => {
  const real = window.fetch;
  let seen = 0;
  window.fetch = (url, opts) => {
    if ((!opts || !opts.method || opts.method === "GET") && String(url).includes(match) && ++seen === nth) {
      return real(url, opts).then((answer) => new Promise((done) => setTimeout(() => done(answer), 1500)));
    }
    return real(url, opts);
  };
}"""


def _imported(studio):
    import httpx
    h = {"X-Agentic-QA": "1"}
    with httpx.Client(base_url=studio.url, headers=h, timeout=30) as c:
        c.post("/api/requirements/connections", json={"id": "jira-main", "product": "jira", "email": EMAIL,
                                                       "site_url": "https://example.atlassian.net",
                                                       "work_item_types": ["Story", "Task"]})
        c.put("/api/requirements/connections/jira-main/token", json={"token": TOKEN})
        job = c.post("/api/requirements/connections/jira-main/imports",
                     json={"mode": "items", "keys": "QPL-2, QPL-3, QPL-4"}).json()
        rapi.JOBS.wait(job["id"])


def test_an_older_explorer_answer_never_overwrites_the_filtered_list(browser, studio):  # noqa: F811
    _imported(studio)
    ctx, page, errors = open_page(browser, studio)
    try:
        slow_nth(page, "/items?kind=jira_issue&q=", 2)  # (the view's SECOND load answers late)
        page.goto(studio.url + "/requirements#explorer")
        expect(page.locator("#exTable tbody tr")).to_have_count(3)  # (first load done: the filters are filled)
        page.evaluate("window.dispatchEvent(new HashChangeEvent('hashchange'))")  # (the view loads again ...)
        page.wait_for_function("document.querySelector('#exTable').getAttribute('aria-busy') === 'true'")
        page.select_option("#exType", "Task")  # (the filtered load starts while the first is still out)
        expect(page.locator("#exTable tbody tr")).to_have_count(1)
        page.wait_for_timeout(2500)  # (the older, unfiltered answer has arrived by now)
        expect(page.locator("#exTable tbody tr")).to_have_count(1)
        expect(page.locator("#exTable tbody")).to_contain_text("QPL-4")
    finally:
        ctx.close()


def test_an_older_connections_answer_never_hides_the_just_saved_token(browser, studio):  # noqa: F811
    ctx, page, errors = open_page(browser, studio)
    try:
        slow_nth(page, "/api/requirements/connections", 2)  # (the view's SECOND load answers late)
        page.goto(studio.url + "/requirements#integrations")
        expect(page.locator("#jiraSite")).to_be_visible()  # (the first load has drawn the cards)
        with page.expect_request(lambda r: r.url.endswith("/api/requirements/connections") and r.method == "GET"):
            page.evaluate("window.dispatchEvent(new HashChangeEvent('hashchange'))")  # (the view loads again)
        page.fill("#jiraSite", "https://example.atlassian.net")
        page.fill("#jiraEmail", EMAIL)
        page.fill("#jiraToken", TOKEN)
        page.get_by_role("button", name="Connect").first.click()
        expect(page.get_by_text("token saved")).to_be_visible()
        page.wait_for_timeout(2500)  # (the first, older answer has arrived by now)
        expect(page.get_by_text("token saved")).to_be_visible()
    finally:
        ctx.close()
