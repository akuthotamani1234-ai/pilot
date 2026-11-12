"""Modal input groups and generated opener chains must work without an AI call."""

import time

import pytest
from playwright.sync_api import sync_playwright

from backend.agents.discovery import EXTRACT_JS
from backend.agents.script_generator import (
    JOURNEY_HELPERS,
    LINES_JS,
    MESSAGES_JS,
    RESULT_HELPERS,
    VALIDATION_JS,
    learned_script,
    validate_script,
)
from backend.agents.test_design import learned_cases
from backend.config import settings
from backend.forms import form_cases, forms_script
from backend.navigation import opener_path
from backend.observe import SNAPSHOT_JS, Explorer

HTML = """<!doctype html><title>Fixture</title>
<button id="contactOpen" type="button" onclick="document.querySelector('#contact').hidden=false">Contact</button>
<section role="dialog" id="contact" hidden aria-label="Contact">
 <label for="email">Email</label><input id="email" type="email" required>
 <label for="name">Name</label><input id="name" type="text" required>
 <label for="message">Message</label><textarea id="message" required></textarea>
 <footer><button id="close" type="button" onclick="document.querySelector('#contact').hidden=true">Close</button>
 <button id="send" type="button" onclick="sendMessage()">Send message</button></footer>
 <div id="error" role="alert"></div>
</section>
<script>window.sent=0;function sendMessage(){
 const email=document.querySelector('#email');
 if(!email.checkValidity()){document.querySelector('#error').textContent='Invalid email';return;}
 window.sent++;fetch('/message',{method:'POST',body:JSON.stringify({email:email.value,name:document.querySelector('#name').value,message:document.querySelector('#message').value})});
}</script>"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    page.route("https://fixture.test/**", lambda route: route.fulfill(content_type="text/html", body=HTML))
    page.goto("https://fixture.test/")
    yield page
    context.close()


def _discover_modal(page, monkeypatch):
    monkeypatch.setattr(settings, "max_interactions_per_page", 8)
    monkeypatch.setattr(settings, "explore_repeated_controls", True)
    monkeypatch.setattr(settings, "discovery_only", False)
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "confirm_writes", False)
    entry = page.evaluate(EXTRACT_JS)
    entry.update(url=page.url, slug="fixture", title="Fixture", page_type="content", auth=False)
    explorer = Explorer(EXTRACT_JS, lambda *args: None, time.time() + 25)
    explorer.explore(page, page.url, entry)
    return entry, explorer


def test_modal_inputs_are_grouped_and_footer_button_is_associated(page):
    assert page.evaluate(EXTRACT_JS)["forms"] == []
    page.locator("#contactOpen").click()
    entry = page.evaluate(EXTRACT_JS)
    form = next(f for f in entry["forms"] if f["selector"] == "#contact")
    assert form["synthetic"] and form["method"] == "script"
    assert {x["selector"] for x in form["fields"]} == {"#email", "#name", "#message"}
    assert form["submit"]["selector"] == "#send"
    send = next(b for b in entry["buttons"] if b["selector"] == "#send")
    assert send["in_form"] and send["type"] == "submit"


def test_discovery_reopens_modal_and_fills_without_submitting(page, monkeypatch):
    entry, explorer = _discover_modal(page, monkeypatch)
    assert next(f for f in entry["forms"] if f["selector"] == "#contact")["revealed_by"] == "#contactOpen"
    explorer.fill_forms(page, page.url, entry)
    record = next(f for f in entry["form_fills"] if f["form"] == "#contact")
    assert len(record["filled"]) == 3, record
    assert not record["sent"] and record.get("not_sent")
    assert page.locator("#email").input_value().endswith("@example.com")
    assert page.locator("#name").input_value()
    assert page.locator("#message").input_value()
    assert page.evaluate("window.sent") == 0
    assert explorer.counts["forms_filled"] == 1


def test_generated_form_replays_modal_and_checks_actual_values(page, monkeypatch):
    entry, _ = _discover_modal(page, monkeypatch)
    cases = form_cases([entry])
    valid = next(c for c in cases if c["id"].startswith("form_valid"))
    assert valid["spec"]["openers"][0]["selector"] == "#contactOpen"
    header = [
        "import re",
        "import pytest",
        "from playwright.sync_api import expect",
        JOURNEY_HELPERS,
        RESULT_HELPERS,
        f"LINES_JS = {LINES_JS!r}",
        f"VALIDATION_JS = {VALIDATION_JS!r}",
        "APPROVE_JS = \"e => e.setAttribute('data-qa-approved', '1')\"",
    ]
    code = forms_script(cases, header)
    assert validate_script(code) is None
    namespace = {}
    exec(compile(code, "generated-modal-form.py", "exec"), namespace)
    guarded = []

    def intercept(route):
        guarded.append({"method": route.request.method, "path": "/message"})
        route.fulfill(json={})

    page.route("**/message", intercept)
    outcome, _ = namespace["_try_form"](page, valid["spec"], "qa-fixture", guarded)
    assert outcome == "sent" and len(guarded) == 1
    assert page.locator("#email").input_value() == "qa-fixture@example.com"
    assert page.locator("#name").input_value() and page.locator("#message").input_value()
    invalid, _ = namespace["_try_form"](page, valid["spec"], "qa-fixture", guarded, bad=("#email", "bad"))
    assert invalid == "refused"
    assert len(guarded) == 1  # validation refused the invalid value without a request


def test_native_form_can_use_a_button_in_its_dialog_footer(page):
    page.set_content("""<dialog open><form id="actual"><label for="field">Name</label><input id="field"></form>
    <footer><button id="save" type="button">Save</button><button type="button">Close</button></footer></dialog>""")
    form = page.evaluate(EXTRACT_JS)["forms"][0]
    assert form["selector"] == "#actual"
    assert form["submit"]["selector"] == "#save"
    assert len(form["fields"]) == 1


def test_generated_learned_action_replays_multiple_openers(page):
    html = """<button id="open" onclick="document.querySelector('#menu').hidden=false">Open</button>
    <div id="menu" hidden><button id="more" onclick="document.querySelector('#submenu').hidden=false">More</button>
    <div id="submenu" hidden><button id="choose" onclick="document.querySelector('#result').textContent='Choice ready'">Choose</button></div></div>
    <p id="result" role="alert"></p>"""
    page.route("https://nested.test/**", lambda route: route.fulfill(content_type="text/html", body=html))
    page.goto("https://nested.test/")
    entry = {
        "slug": "nested",
        "url": page.url,
        "title": "Nested",
        "buttons": [
            {"selector": "#open", "text": "Open"},
            {"selector": "#more", "text": "More", "revealed_by": "#open"},
            {"selector": "#choose", "text": "Choose", "revealed_by": "#more"},
        ],
        "behaviour": [
            {
                "selector": "#choose",
                "control": "Choose",
                "revealed_by": "#more",
                "action": "click",
                "effect": "message",
                "message": "Choice ready",
                "risk": "safe",
                "tone": "ok",
            }
        ],
    }
    cases = learned_cases([entry])
    assert [x["selector"] for x in cases[0]["spec"]["openers"]] == ["#open", "#more"]
    code = learned_script(cases)
    assert validate_script(code) is None
    namespace = {}
    exec(compile(code, "generated-nested.py", "exec"), namespace)
    namespace["_check_learned"](page, [], cases[0]["spec"])
    assert page.locator("#result").inner_text() == "Choice ready"


def test_media_timers_are_not_validation_messages_or_hover_menus(page):
    page.set_content("""<div class="video-js vjs-workinghover" role="region" aria-label="Video Player">
      <div class="vjs-control-bar"><span class="vjs-control" role="status">9:20</span></div>
      <div hidden><p>hidden video controls</p></div></div>
      <p role="alert">Email is required</p>""")
    assert page.evaluate(EXTRACT_JS)["hovers"] == []
    assert page.evaluate(SNAPSHOT_JS, None)["messages"] == ["Email is required"]
    assert page.evaluate(MESSAGES_JS) == ["Email is required"]


def test_cyclic_openers_are_refused():
    entry = {"buttons": [{"selector": "#a", "revealed_by": "#b"}, {"selector": "#b", "revealed_by": "#a"}]}
    with pytest.raises(ValueError, match="cycle"):
        opener_path(entry, "#a")


def test_script_errors_do_not_produce_a_ready_verdict(monkeypatch):
    from backend.agents.reporter import decide_verdict

    monkeypatch.setattr(settings, "gate_max_automation_errors", 0)
    page = {"url": "https://fixture.test", "status": 200, "title": "Fixture"}
    results = [
        {
            "nodeid": "test_checks.py::test_one",
            "file": "test_checks.py",
            "test": "test_one",
            "outcome": "failed",
            "checks": 1,
        }
    ]
    failures = [
        {
            "source": "test",
            "nodeid": results[0]["nodeid"],
            "category": "locator",
            "severity": "medium",
            "test": "test_one",
        }
    ]
    verdict, _, gates = decide_verdict(
        {"url": page["url"], "app_map": [page], "results": results, "failures": failures, "log": []}
    )
    assert verdict == "Insufficient Evidence"
    assert next(g for g in gates if g["id"] == "automation")["status"] == "missing"
    results[0]["outcome"] = "passed"
    _, _, gates = decide_verdict({"url": page["url"], "app_map": [page], "results": results, "failures": [], "log": []})
    assert next(g for g in gates if g["id"] == "automation")["status"] == "pass"


def test_duplicate_label_targets_do_not_turn_a_name_into_an_email(page):
    from backend.testdata import field_kind, valid_value

    page.set_content("""<form>
      <label for="name">Contact Email:</label><input id="email" type="text">
      <label for="name">Contact Name:</label><input id="name" type="text"></form>""")
    inputs = {i["selector"]: i for i in page.evaluate(EXTRACT_JS)["inputs"]}
    assert inputs["#email"]["label"] == "Contact Email:"
    assert inputs["#name"]["label"] == "Contact Name:"
    assert field_kind(inputs["#email"]) == "email"
    assert field_kind(inputs["#name"]) == "names"
    assert "@" not in valid_value(inputs["#name"], "qa-fixture")


def test_similarly_labelled_forms_in_different_dialogs_stay_separate(page):
    page.set_content("""<section id="one" role="dialog"><form><label for="u1">Username</label><input id="u1">
    <input id="p1" type="password"><button type="submit">Log in</button></form></section>
    <section id="two" role="dialog" hidden><form><label for="u2">Username</label><input id="u2">
    <input id="p2" type="password"><button type="submit">Sign up</button></form></section>""")
    entry = {"forms": [], "buttons": [], "inputs": [], "hovers": []}
    explorer = Explorer(EXTRACT_JS, lambda *args: None, time.time() + 20)
    explorer._revealed(page, entry, {"selector": "#open1", "name": "Login"})
    page.locator("#one").evaluate("(e)=>e.hidden=true")
    page.locator("#two").evaluate("(e)=>e.hidden=false")
    explorer._revealed(page, entry, {"selector": "#open2", "name": "Signup"})
    assert len(entry["forms"]) == 2
    assert entry["forms"][0]["selector"] != entry["forms"][1]["selector"]
    assert len(entry["forms"][0]["fields"]) == 2 and len(entry["forms"][1]["fields"]) == 2


def test_whole_form_journey_reopens_modal_before_typing(page, monkeypatch):
    from backend.agents.script_generator import journeys_script
    from backend.agents.test_design import builtin_journeys

    entry, _ = _discover_modal(page, monkeypatch)
    journeys = [c for c in builtin_journeys([entry]) if c.get("journey") == "form"]
    assert journeys and journeys[0]["spec"]["openers"]
    code = journeys_script(journeys)
    assert validate_script(code) is None
    namespace = {}
    exec(compile(code, "generated-form-journey.py", "exec"), namespace)
    namespace["test_" + journeys[0]["id"]](page, [])
    assert page.locator("#email").input_value()
    assert page.locator("#name").input_value()
    assert page.locator("#message").input_value()
    assert page.evaluate("window.sent") == 0
