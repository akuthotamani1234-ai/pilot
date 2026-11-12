"""Going through a website like a user (Nov 2, 2026 - the TestOptim comparison): the menu's sections first, what the
AI saw on the screen is tried too, and every form is filled like a person fills it (sent only on staging)."""
import time

import pytest

from backend.agents.discovery import EXTRACT_JS, _Frontier
from backend.observe import Explorer

TRAVEL = """<!doctype html><html><body><h1>Search flights</h1>
<form id="search-form" method="post" action="/book">
<p><label><input type="radio" name="trip" value="round" id="round" checked> Round trip</label>
<label><input type="radio" name="trip" value="oneway" id="oneway"> One way</label></p>
<p><label for="name">Your name</label> <input id="name" name="name" required></p>
<p><label for="email">E-mail</label> <input id="email" name="email" type="email" required></p>
<p><label for="return">Return date</label> <input type="date" id="return" name="return"></p>
<p><label for="pax">Passengers</label> <select id="pax" name="pax"><option value="">--</option><option>1</option>
<option>2</option></select></p>
<p id="extra"></p>
<button type="submit">Book</button></form>
<form class="oxd-form"><input placeholder="Type here"><button type="submit">In</button></form>
<div class="upgrade" onclick="document.getElementById('extra').textContent='Upgrade options'">Upgrade</div>
<a href="/logout">Log out</a>
<script>
const sync = () => { document.getElementById('return').disabled = !document.getElementById('round').checked; };
document.querySelectorAll('input[name=trip]').forEach(r => r.onchange = sync);
document.getElementById('email').addEventListener('input', () => {
  document.getElementById('extra').innerHTML = '<label for="phone">Phone</label><input id="phone" name="phone">'; });
</script></body></html>"""


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def travel(browser):
    ctx = browser.new_context()
    posted = []

    def answer(route):
        if route.request.method == "POST":
            posted.append(route.request.url)
        route.fulfill(status=200, body=TRAVEL, content_type="text/html")
    ctx.route("http://travel.test/**", answer)
    page = ctx.new_page()
    page.goto("http://travel.test/")
    entry = dict(page.evaluate(EXTRACT_JS), url="http://travel.test/", lazy=False)
    yield page, entry, posted
    ctx.close()


def _explorer():
    return Explorer(EXTRACT_JS, lambda page, ms=0: None, time.time() + 120, tag_base="123456")


def test_the_menu_sections_are_visited_before_deeper_pages():
    q = _Frontier(("https://hr.test/", 0, True, True))
    q.popleft()
    q.append(("https://hr.test/pim/deep/1", 2, True, True))
    q.append_menu(("https://hr.test/recruitment", 1, True, True))
    q.append_menu(("https://hr.test/about", 1, True, False))  # (a visitor's menu: after every logged-in page)
    assert [q.popleft()[0] for _ in range(3)] == ["https://hr.test/recruitment", "https://hr.test/pim/deep/1",
                                                  "https://hr.test/about"]
    q.append_menu(("https://hr.test/maintenance", 1, True, True))
    assert q.menu_left() == ["https://hr.test/maintenance"]  # (what a time limit cut: listed in the report)


def test_what_the_ai_saw_is_tried_but_never_a_form_button_or_log_out(travel):
    page, entry, posted = travel
    entry["seen"] = {"features": [{"name": "Upgrade", "kind": "button"}, {"name": "In", "kind": "button"},
                                  {"name": "Log out", "kind": "account"}, {"name": "Book", "kind": "button"},
                                  {"name": "Main menu", "kind": "navigation"}]}
    ex = _explorer()
    targets = ex._seen_targets(entry, ex._targets(entry))
    names = [t["name"] for t in targets]
    assert "Upgrade" in names and "Main menu" not in names and "Book" not in names, names  # (Book: the page's own)
    ex._explore(page, entry["url"], entry)
    tried = {t["name"]: t["status"] for t in entry["seen_tried"]}
    assert tried.get("Upgrade") == "learned", entry["seen_tried"]
    assert tried.get("In") in ("blocked", None) and tried.get("Log out") in ("blocked", None), entry["seen_tried"]
    assert not posted
    assert any(b["control"] == "Upgrade" for b in entry["behaviour"])  # (it gets a learned test)


def test_every_form_is_filled_like_a_person_and_not_sent_on_a_test_site(travel):
    page, entry, posted = travel
    ex = _explorer()
    assert ex.fill_forms(page, entry["url"], entry) == []
    rec = next(r for r in entry["form_fills"] if r["name"] == "Book")
    filled = {f["box"]: f["value"] for f in rec["filled"]}
    assert filled["Your name"].startswith("QA qa-123456-f") and filled["E-mail"].endswith("@example.com"), filled
    assert "Phone" in rec["appeared"], rec  # (it only appears after the e-mail is typed)
    assert any(f["selector"] for f in next(f for f in entry["forms"] if f["submit"]["text"] == "Book")["fields"]
               if f.get("label") == "Phone")  # (added to the form: its tests fill it too)
    assert any("Return date" in c["turned_off"] for c in rec["choices"]), rec["choices"]  # One way: no return date
    assert rec["sent"] is False and not posted
    punch = next(r for r in entry["form_fills"] if r["name"] == "In")  # the 'In' form: filled and watched, never sent
    assert punch["sent"] is False and "never sent" in punch["not_sent"]


STEPS = '''
from playwright.sync_api import expect

URL = "{url}"


def test_login_steps(page):
    page.goto(URL + "/login")
    page.locator("#username").fill("demo")
    page.locator("#password").fill("Very$ecret-123")
    expect(page.locator("#username")).to_have_value("demo")
    assert page.title()


def test_fails_at_a_step(page):
    page.goto(URL)
    page.locator("#no-such-thing").click(timeout=1500)
'''


@pytest.mark.slow
def test_every_step_of_a_test_is_recorded_and_the_failing_one_marked(tmp_path, monkeypatch):
    """The chat shows the steps of the running test (running.*.json) and every result keeps them (live_steps)."""
    from backend.agents.executor import execution_agent
    from backend.agents.script_generator import TEMPLATES
    from backend.config import settings
    from tests.demo_app import DemoApp
    demo = DemoApp().start()
    try:
        run = tmp_path / "run"
        tests = run / "generated_tests"
        tests.mkdir(parents=True)
        for name in ("conftest.py", "pytest.ini"):
            (tests / name).write_text((TEMPLATES / name).read_text(encoding="utf-8"), encoding="utf-8")
        (tests / "test_steps.py").write_text(STEPS.format(url=demo.url), encoding="utf-8")
        monkeypatch.setattr(settings, "headless", True)
        monkeypatch.setattr(settings, "test_workers", 1)
        monkeypatch.setenv("TEST_PASSWORD", "Very$ecret-123")
        out = execution_agent({"run_dir": str(run), "url": demo.url, "crawl": {"approved_hosts": ["127.0.0.1"]},
                               "log": []})
    finally:
        demo.stop()
    r = {x["test"]: x for x in out["results"]}
    steps = [s["text"] for s in r["test_login_steps"]["live_steps"]]
    assert steps[0] == "Open /login" and "Type 'demo' into" in steps[1], steps
    assert any("[REDACTED]" in s for s in steps) and not any("Very$ecret" in s for s in steps), steps  # (never the password)
    assert any(s.startswith("Check:") for s in steps), steps
    bad = r["test_fails_at_a_step"]["live_steps"]
    assert bad[-1]["ok"] is False and "Click" in bad[-1]["text"], bad  # the step where it failed
    assert "Very$ecret" not in (run / "results.jsonl").read_text(encoding="utf-8")


def test_the_built_in_helpers_pass_the_script_check():
    """The live steps once used getattr() in the journeys' helper: the script check refuses it, so every script with
    the helper was rejected (44 of 49 test cases 'Not automated' on the staging practice run)."""
    from backend.agents import script_generator as sg
    helpers = [n for n in dir(sg) if n.endswith("_HELPERS") and isinstance(getattr(sg, n), str)]
    assert "RESULT_HELPERS" in helpers and "def _step_ok" in sg.RESULT_HELPERS
    for name in helpers:
        code = ("import re\nimport pytest\nfrom playwright.sync_api import expect\n" + getattr(sg, name)
                + "\n\ndef test_x(page):\n    assert True\n")
        assert sg.validate_script(code) is None, (name, sg.validate_script(code))


def test_exploring_does_not_reload_a_page_nothing_changed(browser):
    """Each control is tried as a new visitor sees the page - but a page that is still like that (just opened, or the
    last click changed nothing) is not loaded again: on a slow website every reload cost seconds."""
    page = '''<!doctype html><html><body><h1>Shop</h1><button class="a">Info</button><button class="b">Help</button>
    <button class="c">Tips</button><button class="d" onclick="document.querySelector('h1').textContent='Changed'">
    Change</button><button class="e">More</button></body></html>'''
    ctx = browser.new_context()
    loads = []

    def answer(route):
        if route.request.resource_type == "document":
            loads.append(route.request.url)
        route.fulfill(status=200, body=page, content_type="text/html")
    ctx.route("http://slow.test/**", answer)
    p = ctx.new_page()
    try:
        p.goto("http://slow.test/")
        entry = dict(p.evaluate(EXTRACT_JS), url="http://slow.test/", lazy=False)
        loads.clear()
        ex = _explorer()
        ex._explore(p, entry["url"], entry)
        effects = {b["control"]: b["effect"] for b in entry["behaviour"]}
    finally:
        ctx.close()
    assert effects.get("Change") == "text" and effects.get("Info") == "nothing", effects
    tried = len(entry["behaviour"])
    assert len(loads) < tried, (len(loads), tried)  # (was: one load per control)


def test_ads_and_trackers_are_stopped_but_never_the_website_itself():
    """A page full of ads never goes quiet: every page load waited its full time (automationexercise.com)."""
    from backend.safety import is_ad
    assert is_ad("https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js")
    assert is_ad("https://googleads.g.doubleclick.net/pagead/ads?x=1")
    assert is_ad("https://www.googletagmanager.com/gtm.js?id=1")
    assert not is_ad("https://automationexercise.com/products")
    assert not is_ad("https://shop.example/doubleclick-net-guide")  # (the website's own page about it)


def test_every_test_case_says_its_kind_of_scenario():
    from backend.agents.test_design import scenario_of
    from backend.excel import scenario_counts
    assert scenario_of({"title": "Form 1: submitting it empty is rejected", "type": "negative"}) == "negative"
    assert scenario_of({"title": "Search 'zzzz' shows that nothing was found"}) == "negative"
    assert scenario_of({"title": "Items of /blog: the first, middle and last open", "kind": "items"}) == "edge"
    assert scenario_of({"id": "site_input_values", "title": "Input boxes handle wrong and unusual values"}) == "negative"
    assert scenario_of({"title": "Shopping journey: open it -> add to cart", "journey": "product"}) == "workflow"
    assert scenario_of({"title": "'Attendance' opens its panel", "kind": "learned"}) == "state"
    assert scenario_of({"title": "Sorting by price puts the cheapest first", "kind": "feature"}) == "happy"
    assert scenario_of({"title": "Delete user", "blocked": True}) == "blocked"
    cases = [{"tc_id": "A", "scenario": "happy"}, {"tc_id": "B", "scenario": "negative"}]
    assert scenario_counts(["A", "B"], cases) == "1 happy, 1 negative (no edge)"


def test_severity_follows_what_the_bug_costs():
    from backend.agents.failure_analysis import _business_impact
    total = "E   AssertionError: One more 'Gin' should add 30.5 to the cart total, it went 238.75 -> 238.75"
    assert _business_impact("high", {"test": "test_journey_8"}, total) == "critical"  # money is wrong
    login = "E   AssertionError: Login with the test account did not work: the login form is still shown"
    assert _business_impact("high", {"test": "test_journey_1"}, login) == "critical"  # a core journey is blocked
    js = "E   AssertionError: Logging in and using the app caused JavaScript errors: JS exception: null"
    assert _business_impact("high", {"test": "test_journey_1"}, js) == "high"  # (a coding error: as before)
    wide = "horizontal scroll: the page is 720px wide on a 390px screen"
    assert _business_impact("medium", {"test": "test_mobile_layout"}, wide) == "low"  # cosmetic
    req = "E   AssertionError: Empty form was accepted: the website went on to /thanks without an error message"
    assert _business_impact("medium", {"test": "test_check_3"}, req) == "high"  # a required box not checked
    other = "E   AssertionError: 'Search' changed nothing"
    assert _business_impact("medium", {"test": "test_check_9"}, other) == "medium"


def test_a_form_the_page_script_sends_and_a_box_styled_as_required(browser):
    from backend.forms import data_forms
    page = browser.new_page()
    try:
        page.set_content('<form class="oxd-form"><div><label class="oxd-label oxd-input-field-required">First Name'
                         '</label><input name="firstName"></div><div><label>Nickname</label><input name="nick"></div>'
                         '<button type="submit">Save</button></form>')
        data = page.evaluate(EXTRACT_JS)
    finally:
        page.close()
    form = data["forms"][0]
    assert form["method"] == "script"  # (was: 'get' - left out of the form tests as a search form)
    req = {f["name"]: f["required"] for f in form["fields"]}
    assert req == {"firstName": True, "nick": False}, req
    pages = [dict(data, url="https://hr.test/pim/addEmployee", slug="add", title="PIM", auth=True)]
    assert data_forms(pages), "the form gets its form tests"
