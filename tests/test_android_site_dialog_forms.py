"""Pop-up dialogs in Android Chrome website test mode: a site like demoblaze.com opens Log in, Sign up and Contact as
Bootstrap modals from navbar links. They must be menu entries whose dialog becomes a state, and the dialog's boxes
must be filled and submitted exactly like a page form: sign-up, then login with that account, wrong input refused,
the contact form - with the results listed under the dialog's name.

Lesson from runs/android_20261110_113902_88059d (Android Chrome, https://demoblaze.com, test mode): the page reader's
toggle regex took every Bootstrap `nav-link` for a menu toggle, so "Log in", "Sign up" and "Contact" became "Open the
menu control" checks that only noted "'×' appears"; no dialog state was created, no form was found and nothing was
typed into any box. A second mistake waited behind it: the contact box `#message-text` labelled "Message:" read as
"text message" (an SMS, never sent) and would have excluded the contact form even once the dialog was reached.
"""

import json

import pytest

from backend.android_interact import (
    ACCOUNT_PASSWORD,
    ACCOUNT_USERNAME,
    SIGNUP_EMAIL,
    SIGNUP_USERNAME,
    STRONG_PASSWORD,
    WRONG_PASSWORD,
    label,
)
from backend.android_web import DOM_SCRIPT
from backend.qa_contracts import never_in_test_mode
from tests.android_fake_site import FakeShop
from tests.test_android_site import explore, flow
from tests.test_results_layout import browser as shared_browser

LOGIN, SIGNUP, CONTACT = "'Log in' on Shop. Home — /", "'Sign up' on Shop. Home — /", "'New message' on Shop. Home — /"


@pytest.fixture(scope="module")
def browser():
    yield from shared_browser.__wrapped__()


def has(steps: list[dict], **fields) -> bool:
    """A flow step with these fields (a kept flow's steps carry every optional field, mostly None)."""
    return any(all(step.get(key) == value for key, value in fields.items()) for step in steps)


def css(value: str) -> dict:
    return {"strategy": "css", "value": value}

# demoblaze's start page, reduced to what decides toggle / entry / dialog: the navbar and the open login modal
DEMOBLAZE_LIKE = """
<title>STORE</title>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark" id="narvbarx">
 <a class="navbar-brand" href="index.html" id="nava">PRODUCT STORE</a>
 <button class="navbar-toggler navbar-toggler-right" type="button" data-toggle="collapse" data-target="#navbarExample"
   aria-controls="navbarExample" aria-expanded="false" aria-label="Toggle navigation"><span class="navbar-toggler-icon">x</span></button>
 <div class="collapse navbar-collapse show" id="navbarExample">
  <ul class="navbar-nav ml-auto">
   <li class="nav-item active"><a class="nav-link" href="index.html">Home <span class="sr-only">(current)</span></a></li>
   <li class="nav-item"><a class="nav-link" href="#" data-toggle="modal" data-target="#exampleModal">Contact</a></li>
   <li class="nav-item"><a class="nav-link" href="#" data-toggle="modal" data-target="#videoModal">About us</a></li>
   <li class="nav-item"><a class="nav-link" href="cart.html" id="cartur">Cart</a></li>
   <li class="nav-item"><a class="nav-link" href="#" data-toggle="modal" data-target="#logInModal" id="login2">Log in</a></li>
   <li class="nav-item"><a class="nav-link" href="#" data-toggle="modal" data-target="#signInModal" id="signin2">Sign up</a></li>
   <li class="nav-item dropdown"><a class="nav-link dropdown-toggle" href="#" data-toggle="dropdown" id="dd">More</a></li>
   <li class="menu-item"><a class="menu-link" href="/help">Help</a></li>
  </ul>
 </div>
</nav>
<div class="menu-toggle">Categories</div><div class="sublist-toggle" aria-label="Show the sub-menu"></div>
<button class="hamburger" type="button">x</button><button class="menu-button" type="button">x</button>
<a class="nav-link" href="#" id="fakelink">Phones</a>
<div class="modal fade show" id="logInModal" tabindex="-1" role="dialog" style="display: block">
 <div class="modal-dialog"><div class="modal-content">
  <div class="modal-header"><h5 class="modal-title" id="logInModalLabel">Log in</h5>
   <button type="button" class="close" data-dismiss="modal" aria-label="Close"><span aria-hidden="true">&times;</span></button></div>
  <div class="modal-body">
   <form><!-- an empty form nearby must not claim the boxes below, which sit outside it as on demoblaze --></form>
   <label for="loginusername">Username:</label><input type="text" class="form-control" id="loginusername">
   <label for="loginpassword">Password:</label><input type="password" class="form-control" id="loginpassword">
  </div>
  <div class="modal-footer"><button type="button" class="btn btn-secondary" data-dismiss="modal">Close</button>
   <button type="button" class="btn btn-primary" onclick="logIn()">Log in</button></div>
 </div></div>
</div>
"""


def _run(tmp_path_factory, shop):
    folder = tmp_path_factory.mktemp("dialogs")
    result = explore(folder, shop)
    return {"shop": shop, "result": result, "dir": folder,
            "titles": [item["flow"]["title"] for item in result["auto_flows"]],
            "rows": result["interaction"]["coverage"]}


@pytest.fixture(scope="module")
def dialog_run(tmp_path_factory):
    """Test mode on the demoblaze-like fake, its dialog links flagged opens_dialog as the fixed page reader reports."""
    return _run(tmp_path_factory, FakeShop(dialogs=True))


@pytest.fixture(scope="module")
def bug_run(tmp_path_factory):
    """The same site as the OLD page reader saw it: the dialog links also flagged toggle=True, and Contact a plain
    toggle without the dialog flag. The Python side must still get every dialog form filled."""
    return _run(tmp_path_factory, FakeShop(dialogs=True, toggle_bug=True))


# ------------------------------------------------------------------ 1. the page reader (real Chromium, offline page)

def test_the_page_reader_tells_dialog_openers_and_page_links_from_menu_toggles(browser):
    context = browser.new_context()
    page = context.new_page()
    page.route("https://example.test/**", lambda r: r.fulfill(content_type="text/html", body=DEMOBLAZE_LIKE))
    try:
        page.goto("https://example.test/")
        data = page.evaluate("([script, opts]) => new Function(script)(opts)",
                             [DOM_SCRIPT, {"test_mode": True, "texts": True}])
    finally:
        context.close()
    by = {e["selector"]: e for e in data["elements"]}
    # Links to pages and the navbar's containers are never toggles, whatever menu word their class carries
    for selector in ("#nava", "#cartur", "#navbarExample > ul > li:nth-of-type(1) > a", 'a[href="/help"]', "#fakelink",
                     "#narvbarx", "#navbarExample"):
        assert not by[selector]["toggle"], selector
    # Links that open a dialog are entries with the dialog flag
    for selector in ("#login2", "#signin2", "#navbarExample > ul > li:nth-of-type(2) > a"):
        assert by[selector]["opens_dialog"] and not by[selector]["toggle"] and by[selector]["clickable"], selector
    # Real togglers stay toggles
    for selector in ("button.navbar-toggler.navbar-toggler-right", "#dd", "div.menu-toggle", "div.sublist-toggle",
                     "button.hamburger", "button.menu-button"):
        assert by[selector]["toggle"] and not by[selector]["opens_dialog"], selector
    # The modal: boxes without a <form> grouped under the dialog; "×" and Close come before the type=button submit
    order = [e["selector"] for e in data["elements"] if e["group"] == "#logInModal" and e["region"] == "dialog"]
    assert order.index("button.close") < order.index("#loginusername") < order.index("button.btn.btn-secondary") \
        < order.index("button.btn.btn-primary")
    assert by["#loginusername"]["input"] and by["#loginpassword"]["input_type"] == "password"
    assert by["#loginusername"]["label"] == "Username:" and by["button.close"]["label"] == "Close"
    submit = by["button.btn.btn-primary"]
    assert submit["text"] == "Log in" and submit["clickable"] and not submit["submission"]
    assert [t["text"] for t in data["texts"] if t["region"] == "dialog"][0] == "Log in"  # the state's name


# ------------------------------------------------------------------ 2. the dialog links are entries; dialogs are states

@pytest.mark.parametrize("which", ["dialog_run", "bug_run"])
def test_log_in_and_sign_up_are_menu_entries_never_menu_toggles(which, request):
    run = request.getfixturevalue(which)
    titles = run["titles"]
    assert "Menu entry 'Log in': '×' appears, 'Close' appears" in titles
    assert "Menu entry 'Sign up': '×' appears, 'Close' appears" in titles
    wrong = ("Open the menu 'Log in'", "Open the menu 'Sign up'", "Open the menu control 'Log in'",
             "Open the menu control 'Sign up'")
    assert not any(t.startswith(wrong) for t in titles)
    assert not any(r["name"].startswith(wrong) for r in run["rows"])


def test_a_contact_link_with_the_dialog_flag_is_an_entry(dialog_run):
    assert "Menu entry 'Contact': 'New message' appears, '×' appears" in dialog_run["titles"]


@pytest.mark.parametrize("which", ["dialog_run", "bug_run"])
def test_each_dialog_is_a_state_and_its_forms_run_in_the_order_sign_up_login_contact(which, request):
    run = request.getfixturevalue(which)
    assert {LOGIN, SIGNUP, CONTACT} <= {r.get("where") for r in run["rows"]}
    titles = run["titles"]
    signup = titles.index(f"Sign-up with valid details succeeds on {SIGNUP}")
    login = next(i for i, t in enumerate(titles) if t.startswith("Login with empty fields is refused"))
    contact = titles.index(f"Contact form with valid details succeeds on {CONTACT}")
    assert signup < login < contact


def test_a_real_menu_toggle_that_opens_a_dialog_also_gets_its_form_tested(bug_run):
    """Contact without the dialog flag is a toggle to the reader; the dialog it opens must still become a state."""
    titles = bug_run["titles"]
    assert "Open the menu 'Contact': '×' appears" in titles
    assert f"Contact form with valid details succeeds on {CONTACT}" in titles


# ------------------------------------------------------------------ 3. the forms: every box filled, as on demoblaze

@pytest.mark.parametrize("which", ["dialog_run", "bug_run"])
def test_sign_up_in_the_dialog_registers_then_login_uses_that_account_then_logs_out(which, request):
    run = request.getfixturevalue(which)
    titles = run["titles"]
    signup = flow(run, "Sign-up with valid details succeeds on 'Sign up'")
    taps = [s["locator"]["value"] for s in signup["steps"] if s["action"] == "tap"]
    assert taps[0] == "#signin2" and taps[-1] == "#signInModal button.btn-primary"  # open the dialog, then Sign up
    fills = {s["locator"]["value"]: s.get("secret_ref") for s in signup["steps"] if s["action"] == "fill"}
    assert fills == {"#sign-username": SIGNUP_USERNAME, "#sign-password": STRONG_PASSWORD}
    assert all(s.get("value") is None for s in signup["steps"] if s["action"] == "fill")  # references, never values
    assert has(signup["steps"], action="assert_alert", value="Sign up successful.")

    empty = flow(run, "Login with empty fields is refused")
    assert has(empty["steps"], action="assert_alert", value="Please fill out Username and Password.")
    assert has(empty["steps"], action="assert_visible", locator=css("#loginpassword"))
    wrong = flow(run, "Login with a wrong password is refused")
    assert "Wrong password." in wrong["title"]
    assert {s["locator"]["value"]: s.get("secret_ref") for s in wrong["steps"] if s["action"] == "fill"} == \
        {"#loginusername": ACCOUNT_USERNAME, "#loginpassword": WRONG_PASSWORD}
    login = flow(run, "Login with the account it just registered succeeds")
    assert [s["locator"]["value"] for s in login["steps"] if s["action"] == "tap"][0] == "#login2"
    assert {s["locator"]["value"]: s.get("secret_ref") for s in login["steps"] if s["action"] == "fill"} == \
        {"#loginusername": ACCOUNT_USERNAME, "#loginpassword": ACCOUNT_PASSWORD}
    last = login["steps"][-1]
    assert last["action"] == "assert_not_visible" and last["locator"] == css("#loginpassword")  # the dialog closed
    assert "Log out with 'Log out': 'Log in' appears, 'Sign up' appears" in titles


def test_the_contact_dialog_is_filled_and_sent_and_its_missing_validation_is_a_finding(dialog_run):
    contact = flow(dialog_run, f"Contact form with valid details succeeds on {CONTACT}")
    fills = {s["locator"]["value"]: s for s in contact["steps"] if s["action"] == "fill"}
    assert set(fills) == {"#recipient-email", "#recipient-name", "#message-text"}
    assert fills["#recipient-email"].get("secret_ref") == SIGNUP_EMAIL
    assert fills["#recipient-name"]["value"] and fills["#message-text"]["value"]
    assert has(contact["steps"], action="assert_alert", value="Thanks for the message!!")
    # demoblaze thanks for an empty message too: recorded as a finding, not hidden
    findings = {f["finding"] for f in dialog_run["result"]["interaction"]["findings"] if f["screen"] == CONTACT}
    assert {"Submitting the form empty was accepted",
            "An invalid email ('qa.tester') in 'Contact Email:' was accepted"} <= findings
    row = next(r for r in dialog_run["rows"] if r["name"] == "Submitting the form empty is refused" and r["where"] == CONTACT)
    assert row["status"] == "failed"


def test_a_box_label_the_reader_repeats_does_not_read_as_checkout():
    """The web reader gives a box's label twice (accessibility_id and hint); joined with the id "message-text".
    That must not look like a blocked checkout/payment control."""
    box = {"text": "", "accessibility_id": "Message:", "resource_id": "message-text", "hint": "Message:"}
    assert label(box) == "Message: message-text"
    assert never_in_test_mode(label(box)) == ""
    assert never_in_test_mode("Checkout") and never_in_test_mode("Place order")


# ------------------------------------------------------------------ 4. nothing private leaves .private, nothing risky

@pytest.mark.parametrize("which", ["dialog_run", "bug_run"])
def test_the_account_name_and_password_stay_in_the_private_folder(which, request):
    run = request.getfixturevalue(which)
    saved = json.loads((run["dir"] / ".private" / "auto_secrets.json").read_text(encoding="utf-8"))
    user, password = saved[ACCOUNT_USERNAME], saved[ACCOUNT_PASSWORD]
    assert user.startswith("qa") and run["shop"].accounts[user] == password
    public = json.dumps(run["result"]["auto_flows"]) + json.dumps(run["rows"]) \
        + json.dumps(run["result"]["interaction"]["tried"])
    assert user not in public and password not in public
    for name in ("screens.json", "android_discovery.json", "android_interaction.json", "auto_flows.json"):
        text = (run["dir"] / name).read_text(encoding="utf-8")
        assert user not in text and password not in text, name
    assert not any("Welcome" in t for t in run["titles"])  # "Welcome qa..." names the account: never a test title


@pytest.mark.parametrize("which", ["dialog_run", "bug_run"])
def test_the_old_menu_toggles_stay_toggles_and_checkout_is_never_pressed(which, request):
    run = request.getfixturevalue(which)
    for title in ("Open the menu 'Categories': 'Computers' appears",
                  "Open the menu 'Show the Computers sub-menu': 'Desktops' appears",
                  "Open the menu 'Information': 'About us' appears"):
        assert title in run["titles"], title
    pressed = " ".join(run["shop"].pressed).casefold()
    assert "checkout" not in pressed and "place order" not in pressed
