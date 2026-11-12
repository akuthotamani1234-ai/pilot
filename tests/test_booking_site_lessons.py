"""What the run on automationintesting.online (runs/automationintesting.online_20261101_180846) got wrong - each one
fixed and kept fixed here (the pages below are built like the ones there):
  * the 'Check In' / 'Check Out' date boxes were found by the date written in them (input[value="01/11/2026"]):
    once a test typed into a box the address found nothing (22 tests could not find their box), and the next day
    it would find nothing at all;
  * clicking 'Login' with empty boxes ('Invalid credentials') was reported as a website bug: the login button is
    tested by 'Login with a wrong password is rejected' - its learned test said an error message is never right."""
import pytest


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def test_a_date_box_is_not_found_by_the_date_written_in_it(browser):
    from backend.agents.discovery import EXTRACT_JS
    page = browser.new_page()
    try:
        page.set_content('<!doctype html><html><body><h1>Book a room</h1><form>'
                         '<label>Check In<input class="form-control" type="text" value="01/11/2026"></label>'
                         '<label>Check Out<input class="form-control" type="text" value="02/11/2026"></label>'
                         '<label><input type="radio" name="room" value="single">Single</label>'
                         '<label><input type="radio" name="room" value="double">Double</label>'
                         '<button type="button">Check Availability</button></form></body></html>')
        boxes = {i.get("label"): i["selector"] for i in page.evaluate(EXTRACT_JS)["inputs"]}
        assert not [s for s in (boxes["Check In"], boxes["Check Out"]) if "[value=" in s], boxes
        page.locator(boxes["Check In"]).first.fill("05/11/2026")  # (typing changes what is written in it)
        assert page.locator(boxes["Check In"]).count() >= 1 and page.locator(boxes["Check Out"]).count() >= 1
        assert page.locator(boxes["Check In"]).first.input_value() == "05/11/2026"
        assert page.locator(boxes["Check Out"]).first.input_value() == "02/11/2026"
        # radios sharing a name are still told apart by their value (it never changes)
        assert (boxes["Single"], boxes["Double"]) == ('input[name="room"][value="single"]',
                                                      'input[name="room"][value="double"]'), boxes
    finally:
        page.close()


def test_the_login_button_gets_no_learned_test_its_wrong_password_test_covers_it():
    from backend.agents.test_design import control_cases, learned_cases
    p = {"url": "https://booking.test/admin", "slug": "admin", "title": "Admin", "auth": False, "status": 200,
         "page_type": "login", "forms": [], "links": [], "itemNames": [],
         "inputs": [{"tag": "input", "type": "text", "id": "username", "name": "", "selector": "#username",
                     "label": "Username", "role": "textbox"},
                    {"tag": "input", "type": "password", "id": "password", "name": "", "selector": "#password",
                     "label": "Password", "role": "textbox"}],
         "buttons": [{"tag": "button", "type": "submit", "text": "Login", "selector": "#doLogin", "role": "button"}],
         "behaviour": [{"control": "Login", "selector": "#doLogin", "effect": "nothing", "action": "click",
                        "risk": "safe"}]}
    assert not [c for c in learned_cases([p]) if c["spec"]["selector"] == "#doLogin"]
    assert [c for c in control_cases(p) if c["kind"] == "login_wrong"]  # (the login button is still tested)
