"""P2 form boundaries and target identity (offline HTML fixtures).

Lessons from OrangeHRM-style pages: a sidebar Search must never receive a form phone fill; duplicate labels are
resolved by their form/dialog/section container; unresolved ambiguous matches are automation/inconclusive (fail
closed, never a quiet Playwright .first pick); missing required fields or a wrong opener mean the whole-form check
cannot pass. Sidebar search and table row checkboxes stay out of form schemas.
"""
import ast
import time

import pytest
from playwright.sync_api import sync_playwright

from backend.agents.discovery import EXTRACT_JS
from backend.agents.script_generator import (
    JOURNEY_HELPERS,
    LINES_JS,
    RESULT_HELPERS,
    VALIDATION_JS,
    journeys_script,
    validate_script,
)
from backend.agents.test_design import builtin_journeys
from backend.forms import (
    FORM_HELPERS,
    data_forms,
    form_cases,
    form_scope,
    forms_script,
    keep_form_field,
    unique_field,
)
from backend.observe import Explorer
from backend.testdata import field_kind, valid_value

# Sidebar Search + Emergency Contact form + a contacts table with row checkboxes.
EC_HTML = """<!doctype html><title>Contacts</title>
<aside id="sidebar" class="sidebar" role="complementary">
  <label for="globalSearch">Search</label>
  <input id="globalSearch" type="search" name="q" placeholder="Search">
</aside>
<main>
  <button id="openAdd" type="button"
    onclick="document.querySelector('#addDialog').hidden=false">Add</button>
  <section role="dialog" id="addDialog" hidden aria-label="Add Emergency Contact">
    <form id="emergency" method="post" action="/save">
      <label for="ecName">Name</label><input id="ecName" name="name" required>
      <label for="ecRel">Relationship</label><input id="ecRel" name="relationship" required>
      <label for="ecPhone">Home Telephone</label><input id="ecPhone" name="homePhone" type="tel" required>
      <label for="ecMobile">Mobile</label><input id="ecMobile" name="mobile" type="tel">
      <label for="ecEmail">E-mail</label><input id="ecEmail" name="email" type="email">
      <button id="saveEc" type="submit">Save</button>
    </form>
  </section>
  <table id="contacts"><thead><tr><th></th><th>Name</th></tr></thead>
    <tbody>
      <tr><td><input class="row-check" type="checkbox" aria-label="Select Alice"></td><td>Alice</td></tr>
      <tr><td><input class="row-check" type="checkbox" aria-label="Select Bob"></td><td>Bob</td></tr>
    </tbody>
  </table>
</main>"""

DUP_OK_HTML = """<!doctype html><title>Dup ok</title>
<section role="dialog" id="one" aria-label="Login">
  <form id="loginForm"><label for="u1">Username</label><input id="u1" name="username" required>
  <button type="submit">Log in</button></form>
</section>
<section role="dialog" id="two" aria-label="Profile">
  <form id="profileForm"><label for="u2">Username</label><input id="u2" name="username" required>
  <button type="submit">Save</button></form>
</section>"""

DUP_BAD_HTML = """<!doctype html><title>Dup bad</title>
<form id="messy">
  <label>Phone</label><input class="shared" name="a">
  <label>Phone</label><input class="shared" name="b">
  <button type="submit">Save</button>
</form>"""

MISSING_REQ_HTML = """<!doctype html><title>Missing</title>
<form id="partial">
  <label for="only">Nickname</label><input id="only" name="nick">
  <button type="submit">Save</button>
</form>"""


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
    yield page
    context.close()


def _exec_form_helpers():
    ns = {}
    header = (
        "import re\nimport pytest\nfrom playwright.sync_api import expect\n"
        + JOURNEY_HELPERS + "\n" + RESULT_HELPERS + "\n"
        + f"LINES_JS = {LINES_JS!r}\nVALIDATION_JS = {VALIDATION_JS!r}\n"
        + "APPROVE_JS = \"e => e.setAttribute('data-qa-approved', '1')\"\n"
    )
    exec(compile(header + FORM_HELPERS, "form-helpers.py", "exec"), ns)
    return ns


def test_discovery_excludes_sidebar_search_and_table_checkboxes_from_form_schema(page):
    page.set_content(EC_HTML)
    page.locator("#openAdd").click()
    data = page.evaluate(EXTRACT_JS)
    form = next(f for f in data["forms"] if f["selector"] in ("#emergency", "#addDialog"))
    sels = {x["selector"] for x in form["fields"]}
    assert "#ecPhone" in sels and "#globalSearch" not in sels
    assert not any("row-check" in (x.get("selector") or "") for x in form["fields"])
    side = next(i for i in data["inputs"] if i["selector"] == "#globalSearch")
    assert side.get("chrome") or side.get("region") == "sidebar"
    assert field_kind(next(x for x in form["fields"] if x["selector"] == "#ecPhone")) == "phone"
    assert field_kind(next(x for x in form["fields"] if x["selector"] == "#ecEmail")) == "email"


def test_data_forms_drops_chrome_search_and_keeps_phone_kind(page):
    page.set_content(EC_HTML)
    page.locator("#openAdd").click()
    data = page.evaluate(EXTRACT_JS)
    # Poison the form schema the way a wrapping <form> might: inject sidebar search + row checkbox.
    form = next(f for f in data["forms"] if "#ecPhone" in {x["selector"] for x in f["fields"]}
                or f["selector"] in ("#emergency", "#addDialog"))
    form["fields"] = list(form["fields"]) + [
        {"selector": "#globalSearch", "type": "search", "label": "Search", "chrome": True, "region": "sidebar"},
        {"selector": "tbody .row-check >> nth=0", "type": "checkbox", "label": "Select Alice", "in_table": True},
    ]
    form.setdefault("submit", {"text": "Save", "selector": "#saveEc"})
    form["method"] = "post"
    pages = [dict(data, url="https://hr.test/pim/contact", slug="contact", title="Contacts", auth=True,
                  page_type="admin", forms=[form])]
    found = data_forms(pages)
    assert found, "emergency contact remains a data form"
    boxes = {b["selector"]: b for b in found[0]["boxes"]}
    assert "#globalSearch" not in boxes and not any("row-check" in s for s in boxes)
    assert boxes["#ecPhone"]["kind"] == "phone"
    assert boxes["#ecEmail"]["kind"] == "email"
    assert keep_form_field({"selector": "#globalSearch", "type": "search", "chrome": True, "label": "Search"}) is False


def test_filling_phone_never_types_into_sidebar_search(page):
    page.set_content(EC_HTML)
    page.locator("#openAdd").click()
    data = page.evaluate(EXTRACT_JS)
    form = next(f for f in data["forms"] if any(x.get("selector") == "#ecPhone" for x in f.get("fields", [])))
    form["revealed_by"] = "#openAdd"
    # Broad selector that would also match the sidebar if scoped to the page (fail-closed / container test).
    ns = _exec_form_helpers()
    spec = {
        "url": "about:blank", "form": "#emergency", "submit": "#saveEc", "submit_text": "Save",
        "openers": [], "required_fields": [{"selector": "input", "name": "Home Telephone", "kind": "phone"}],
        "boxes": [
            {"selector": "#ecName", "name": "Name", "kind": "names", "type": "text", "tag": "input",
             "required": True, "valid": "QA {tag}", "tagged": True, "label": "Name"},
            {"selector": "#ecRel", "name": "Relationship", "kind": "text", "type": "text", "tag": "input",
             "required": True, "valid": "QA {tag}", "tagged": True, "label": "Relationship"},
            {"selector": "input", "name": "Home Telephone", "kind": "phone", "type": "tel", "tag": "input",
             "required": True, "valid": "+1 555 010 0199", "tagged": False, "label": "Home Telephone"},
            {"selector": "#ecMobile", "name": "Mobile", "kind": "phone", "type": "tel", "tag": "input",
             "required": False, "valid": "+1 555 010 0199", "tagged": False, "label": "Mobile"},
            {"selector": "#ecEmail", "name": "E-mail", "kind": "email", "type": "email", "tag": "input",
             "required": False, "valid": "{tag}@example.com", "tagged": True, "label": "E-mail"},
        ],
    }
    page.locator("#openAdd").click()
    ns["_fill_form"](page, spec, "qa-boundary")
    assert page.locator("#globalSearch").input_value() == ""
    assert page.locator("#ecPhone").input_value() == "+1 555 010 0199"
    assert "@" in page.locator("#ecEmail").input_value()


def test_duplicate_labels_resolved_by_container(page):
    page.set_content(DUP_OK_HTML)
    scope = form_scope(page, {"form": "#profileForm"})
    el = unique_field(page, scope, {"selector": "input[name=username]", "name": "Username", "label": "Username",
                                    "required": True, "type": "text"})
    el.fill("profile-user")
    assert page.locator("#u2").input_value() == "profile-user"
    assert page.locator("#u1").input_value() == ""


def test_unresolved_ambiguous_is_inconclusive_not_pass(page):
    page.set_content(DUP_BAD_HTML)
    ns = _exec_form_helpers()
    notes = []
    ns["_inconclusive"] = lambda reason: notes.append(reason)
    spec = {
        "url": "about:blank", "form": "#messy", "submit": "button[type=submit]", "submit_text": "Save",
        "openers": [], "mode": "guard",
        "required_fields": [],
        "boxes": [
            {"selector": "input.shared", "name": "Phone", "kind": "phone", "type": "text", "tag": "input",
             "required": True, "valid": "+1 555 010 0199", "tagged": False, "label": "Phone"},
        ],
    }
    with pytest.raises(ns["FormTargetProblem"]) as raised:
        ns["_fill_form"](page, spec, "qa-ambig")
    assert raised.value.kind == "ambiguous"
    # Whole-form valid check converts ambiguous into inconclusive (not a pass).
    ns["_try_form"] = lambda *a, **k: (_ for _ in ()).throw(ns["_form_target_problem"]("ambiguous", "two Phones"))
    ns["_check_valid"](page, spec, "qa-ambig")
    assert notes and ("ambiguous" in notes[0].lower() or "two Phones" in notes[0])


def test_missing_required_field_blocks_whole_form_pass(page):
    page.set_content(MISSING_REQ_HTML)
    ns = _exec_form_helpers()
    spec = {
        "url": "about:blank", "form": "#partial", "submit": "button[type=submit]", "submit_text": "Save",
        "openers": [], "required_fields": [{"selector": "#gone", "name": "Full name", "kind": "names"}],
        "boxes": [
            {"selector": "#only", "name": "Nickname", "kind": "names", "type": "text", "tag": "input",
             "required": False, "valid": "QA {tag}", "tagged": True, "label": "Nickname"},
            {"selector": "#gone", "name": "Full name", "kind": "names", "type": "text", "tag": "input",
             "required": True, "valid": "QA {tag}", "tagged": True, "label": "Full name"},
        ],
    }
    with pytest.raises(AssertionError, match="whole-form check cannot pass"):
        ns["_fill_form"](page, spec, "qa-missing")


def test_wrong_opener_blocks_whole_form_pass(page):
    page.set_content(EC_HTML)  # dialog starts hidden; wrong opener never reveals it
    ns = _exec_form_helpers()
    spec = {
        "url": "about:blank", "form": "#emergency", "submit": "#saveEc", "submit_text": "Save",
        "openers": [{"selector": "#globalSearch", "action": "click", "name": "Search"}],
        "required_fields": [{"selector": "#ecName", "name": "Name"}],
        "boxes": [
            {"selector": "#ecName", "name": "Name", "kind": "names", "type": "text", "tag": "input",
             "required": True, "valid": "QA {tag}", "tagged": True, "label": "Name"},
        ],
    }
    # open_path expects the target after the opener; wrong opener leaves the form hidden → cannot pass.
    from playwright.sync_api import Error as PlaywrightError
    with pytest.raises((PlaywrightError, AssertionError)):
        ns["open_path"](page, spec["openers"], "#ecName")
    assert page.locator("#emergency").is_hidden() or not page.locator("#ecName").is_visible()


def test_form_cases_preserve_opener_path_and_required_fields(page, monkeypatch):
    from backend.config import settings
    page.route("https://fixture.test/**", lambda route: route.fulfill(content_type="text/html", body=EC_HTML))
    page.goto("https://fixture.test/")
    monkeypatch.setattr(settings, "max_interactions_per_page", 8)
    monkeypatch.setattr(settings, "explore_repeated_controls", True)
    monkeypatch.setattr(settings, "discovery_only", False)
    monkeypatch.setattr(settings, "environment", "test")
    monkeypatch.setattr(settings, "confirm_writes", False)
    entry = page.evaluate(EXTRACT_JS)
    entry.update(url=page.url, slug="contacts", title="Contacts", page_type="content", auth=False)
    Explorer(EXTRACT_JS, lambda *a: None, time.time() + 20).explore(page, page.url, entry)
    cases = form_cases([entry])
    assert cases, [c.get("title") for c in (entry.get("forms") or [])]
    valid = next(c for c in cases if c["id"].startswith("form_valid"))
    assert valid["spec"]["openers"], "Add dialog opener path must be preserved"
    assert valid["spec"]["openers"][0]["selector"] == "#openAdd"
    assert valid["spec"]["required_fields"]
    assert any(b.get("kind") == "phone" for b in valid["spec"]["boxes"])
    code = forms_script(cases, [
        "import re", "import pytest", "from playwright.sync_api import expect",
        JOURNEY_HELPERS, RESULT_HELPERS,
        f"LINES_JS = {LINES_JS!r}", f"VALIDATION_JS = {VALIDATION_JS!r}",
        "APPROVE_JS = \"e => e.setAttribute('data-qa-approved', '1')\"",
    ])
    assert validate_script(code) is None
    assert "_unique_field" in code and "FormTargetProblem" in code


def test_journey_form_script_scopes_and_tracks_required(page, monkeypatch):
    from backend.config import settings
    page.route("https://fixture.test/**", lambda route: route.fulfill(content_type="text/html", body=EC_HTML))
    page.goto("https://fixture.test/")
    monkeypatch.setattr(settings, "max_interactions_per_page", 8)
    monkeypatch.setattr(settings, "explore_repeated_controls", True)
    monkeypatch.setattr(settings, "discovery_only", False)
    monkeypatch.setattr(settings, "environment", "test")
    entry = page.evaluate(EXTRACT_JS)
    entry.update(url=page.url, slug="contacts", title="Contacts", page_type="content", auth=False)
    Explorer(EXTRACT_JS, lambda *a: None, time.time() + 20).explore(page, page.url, entry)
    journeys = [c for c in builtin_journeys([entry]) if c.get("journey") == "form"]
    if not journeys:
        # Force a form journey from the discovered emergency form when field count is high enough.
        form = next(f for f in entry["forms"] if any(x.get("id") == "ecPhone" for x in f.get("fields", [])))
        from backend.agents.test_design import _form_fields
        fields = _form_fields(entry, form)
        assert len(fields) >= 3
        journeys = [{
            "id": "journey_1", "kind": "journey", "journey": "form", "guest": True,
            "title": "Fill emergency contact", "spec": {
                "url": entry["url"], "form": form["selector"], "fields": fields,
                "required_fields": [{"selector": x["selector"], "name": x["name"]} for x in fields if x.get("required")],
                "openers": [{"selector": "#openAdd", "action": "click", "name": "Add"}],
            },
        }]
    code = journeys_script(journeys)
    assert validate_script(code) is None
    assert "unique_field" in code and "form_scope" in code
    assert "required_fields" in code or "whole-form check cannot pass" in code
    tree = ast.parse(code)
    assert any(isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in tree.body)


def test_field_kind_phone_and_email_values_fit(page):
    page.set_content(EC_HTML)
    page.locator("#openAdd").click()
    inputs = {i["selector"]: i for i in page.evaluate(EXTRACT_JS)["inputs"]}
    assert field_kind(inputs["#ecPhone"]) == "phone"
    assert field_kind(inputs["#ecEmail"]) == "email"
    assert valid_value(inputs["#ecPhone"], "qa-x").replace(" ", "").lstrip("+").isdigit() or "+" in valid_value(
        inputs["#ecPhone"], "qa-x")
    assert "@" in valid_value(inputs["#ecEmail"], "qa-x")
