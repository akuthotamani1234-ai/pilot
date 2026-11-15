"""Offline acceptance shapes for Android form reliability (Spinners, ambiguity, catalog oracles, session loss)."""
import json
import time
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import quoteattr

from backend.android import extract_screen
from backend.android_design import normalize_screens
from backend.android_events import Timeline
from backend.android_interact import (
    Session,
    build_form,
    catalog_fields,
    find_form,
    preferred_locator,
    select_choice,
    submit_candidates,
)
from backend.android_runtime import device_unavailable

PACKAGE = "com.example.catalogfixture"


def node(cls, *, text="", resource="", desc="", hint="", password=False, clickable=False, checkable=False,
         checked=False, bounds="[0,100][400,160]", children=""):
    attrs = {"class": cls, "package": PACKAGE, "text": text, "resource-id": resource, "content-desc": desc,
             "hint": hint, "password": str(password).lower(), "clickable": str(clickable).lower(),
             "checkable": str(checkable).lower(), "checked": str(checked).lower(),
             "enabled": "true", "displayed": "true", "bounds": bounds}
    return "<node " + " ".join(k + "=" + quoteattr(v) for k, v in attrs.items()) + ">" + children + "</node>"


def catalog_xml(*, name_text="", country_text="Select country", submit_labels=("Continue",),
                extra_submit=False, products_open=False):
    body = node("android.widget.TextView", text="Welcome", resource=PACKAGE + ":id/title", bounds="[0,20][400,60]")
    if products_open:
        body = node("android.widget.TextView", text="Products", resource=PACKAGE + ":id/title", bounds="[0,20][400,60]")
        body += node("androidx.recyclerview.widget.RecyclerView", resource=PACKAGE + ":id/productRV",
                     desc="Displays all products of catalog", bounds="[0,80][400,700]")
        return "<hierarchy>" + node("android.widget.FrameLayout", bounds="[0,0][400,800]", children=body) + "</hierarchy>"
    body += node("android.widget.Spinner", text=country_text, resource=PACKAGE + ":id/countrySpinner",
                 desc="Country", clickable=True, bounds="[20,80][380,140]")
    body += node("android.widget.EditText", resource=PACKAGE + ":id/nameET", hint="Name", text=name_text,
                 bounds="[20,160][380,220]")
    body += node("android.widget.RadioButton", text="Female", resource=PACKAGE + ":id/genderFemale",
                 clickable=True, checkable=True, bounds="[20,240][180,290]")
    body += node("android.widget.RadioButton", text="Male", resource=PACKAGE + ":id/genderMale",
                 clickable=True, checkable=True, bounds="[200,240][360,290]")
    labels = list(submit_labels)
    if extra_submit:
        labels.append("Go")
    top = 320
    for index, label in enumerate(labels):
        body += node("android.widget.Button", text=label, resource=PACKAGE + f":id/submit{index}",
                     clickable=True, bounds=f"[20,{top}][380,{top + 50}]")
        top += 70
    return "<hierarchy>" + node("android.widget.ScrollView", resource=PACKAGE + ":id/formScroll",
                                bounds="[0,0][400,800]", children=body) + "</hierarchy>"


def screen_from(xml, activity=".MainActivity"):
    return normalize_screens([extract_screen(xml, PACKAGE, "emulator-5554", activity)])[0]


def test_spinner_and_radio_are_classified_as_choices():
    screen = screen_from(catalog_xml())
    kinds = {(e["type"], e.get("choice_kind")) for e in screen["elements"] if e["visible"]}
    assert ("choice", "spinner") in kinds
    assert ("choice", "radio") in kinds
    assert any(e["input_capable"] and "name" in (e.get("hint") or "").casefold() for e in screen["elements"])


def test_preferred_locator_keeps_unique_ranking():
    # Unique resource_id is ranked first at extract time.
    unique = screen_from(catalog_xml())
    name = next(e for e in unique["elements"] if e.get("hint") == "Name")
    assert preferred_locator(name)["strategy"] == "resource_id"
    # Contextual xpath that disambiguates a shared resource_id must stay first.
    disambiguated = {"locators": [
        {"strategy": "xpath",
         "value": f"//*[@text='Sauce Labs Backpack']/..//*[@resource-id='{PACKAGE}:id/productIV']"},
        {"strategy": "resource_id", "value": PACKAGE + ":id/productIV"}]}
    assert preferred_locator(disambiguated)["strategy"] == "xpath"


def test_zero_submit_candidates_marks_form_incomplete():
    screen = screen_from(catalog_xml(submit_labels=()))
    # Remove accidental near-input clicks by clearing clickable non-choice controls without labels matching SUBMIT.
    for element in screen["elements"]:
        if element.get("type") == "button":
            element["clickable"] = False
            element["visible"] = False
    form = find_form(screen)
    assert form is not None and form["kind"] == "incomplete" and form["submit_status"] == "missing"


def test_ambiguous_submit_candidates_are_reported_not_guessed():
    screen = screen_from(catalog_xml(submit_labels=("Continue", "Next")))
    form = find_form(screen)
    assert form["kind"] == "ambiguous" and form["submit_status"] == "ambiguous"
    assert len(form["submit_candidates"]) >= 2
    session = Session(SimpleNamespace(config={"app_mode": "installed"}, screens=[screen], driver=None,
                                      stop_path=SimpleNamespace(exists=lambda: False),
                                      deadline=time.monotonic() + 60, max_tries=30))
    session.form_checks(screen, form)
    assert any(item.get("outcome") == "inconclusive" and "AMBIGUITY" in item.get("detail", "")
               for item in session.tried)


def test_single_near_input_unfamiliar_button_is_usable_evidence():
    screen = screen_from(catalog_xml(submit_labels=()))
    mystery = {
        "id": "mystery", "type": "button", "class_name": "android.widget.Button", "text": "",
        "accessibility_id": "", "resource_id": PACKAGE + ":id/mystery", "hint": "",
        "visible": True, "enabled": True, "clickable": True, "input_capable": False,
        "locator_unique": True, "within_webview": False, "outside_active_drawer": False,
        "outside_active_dialog": False, "navigation_role": "", "bounds": "[20,320][380,370]",
        "locators": [{"strategy": "resource_id", "value": PACKAGE + ":id/mystery"}],
    }
    screen["elements"].append(mystery)
    inputs = [e for e in screen["elements"] if e.get("input_capable")]
    candidates = submit_candidates(screen, inputs)
    assert len(candidates) == 1 and candidates[0]["resource_id"].endswith("mystery")


def test_catalog_fields_detect_country_name_gender_chain():
    screen = screen_from(catalog_xml())
    form = find_form(screen)
    assert form["kind"] == "catalog"
    fields = catalog_fields(form["inputs"], form["choices"])
    assert fields["country"]["choice_kind"] == "spinner"
    assert "name" in (fields["name"].get("hint") or "").casefold()
    assert len(fields["gender"]) >= 2
    steps = select_choice(fields["country"], "United States")
    assert steps[0]["action"] == "tap" and steps[-1]["action"] == "assert_text"
    assert steps[-1]["value"] == "United States"
    assert preferred_locator(fields["country"])["strategy"] == "resource_id"


def test_catalog_empty_name_and_valid_oracles(monkeypatch):
    form_screen = screen_from(catalog_xml())
    products = screen_from(catalog_xml(products_open=True))
    form = find_form(form_screen)
    device = SimpleNamespace(config={"app_mode": "installed"}, screens=[form_screen], driver=None,
                             stop_path=SimpleNamespace(exists=lambda: False),
                             deadline=time.monotonic() + 60, max_tries=30)
    session = Session(device)
    calls = []

    def observe(screen, steps, **kwargs):
        calls.append(steps)
        # First call: empty name stays on form with validation text injected.
        if len(calls) == 1:
            after = json.loads(json.dumps(form_screen))
            after["elements"].append({"id": "err", "type": "text", "text": "Name is required", "visible": True,
                                      "class_name": "android.widget.TextView", "resource_id": PACKAGE + ":id/error",
                                      "accessibility_id": "", "locators": [
                                          {"strategy": "resource_id", "value": PACKAGE + ":id/error"}],
                                      "locator_unique": True, "input_capable": False, "within_webview": False,
                                      "outside_active_drawer": False, "outside_active_dialog": False})
            return form_screen, after
        return form_screen, products

    kept = []
    monkeypatch.setattr(session, "observe_after", observe)
    monkeypatch.setattr(session, "keep", lambda flow, meta, **kwargs: kept.append((flow, meta)) or True)
    monkeypatch.setattr(session, "_messages", lambda before, after: (
        [{"action": "assert_visible", "locator": {"strategy": "resource_id", "value": PACKAGE + ":id/error"}}],
        [{"kind": "message", "after": "Name is required", "element": {"text": "Name is required"}}]))
    session.form_checks(form_screen, form)
    assert len(calls) == 2
    assert any(meta.get("setup_chain") == "catalog_country_name_gender" for _, meta in kept)
    # Valid path must assert products, not merely that the form disappeared.
    valid_flow = kept[-1][0]
    assert any(step.get("action") == "assert_text" and "Products" in str(step.get("value", ""))
               for step in valid_flow["steps"]) or any(
        step.get("action") == "assert_visible" and "productRV" in str(step.get("locator", {}))
        for step in valid_flow["steps"])
    # Empty-name path must not treat products as success.
    assert not session.products_accessible(form_screen)


def test_form_disappearance_alone_is_not_success(monkeypatch):
    login = screen_from(catalog_xml())  # reuse structure but force generic form
    # Strip choices so it is a plain form with name + continue.
    for element in login["elements"]:
        if element.get("type") == "choice":
            element["visible"] = False
            element["enabled"] = False
    form = find_form(login)
    assert form and form["kind"] == "form"
    device = SimpleNamespace(config={"app_mode": "installed"}, screens=[login], driver=None,
                             stop_path=SimpleNamespace(exists=lambda: False),
                             deadline=time.monotonic() + 60, max_tries=30)
    session = Session(device)
    after = json.loads(json.dumps(login))
    after["elements"] = [e for e in after["elements"] if not e.get("input_capable")]
    after["screen_name"] = "Somewhere else"
    monkeypatch.setattr(session, "observe_after", lambda *a, **k: (login, after))
    monkeypatch.setattr(session, "keep", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not keep")))
    session._positive_form_check(login, form, "Form submission")
    assert any(item.get("outcome") == "finding" and "meaningful success" in item.get("reason", "")
               for item in session.tried)


def test_session_loss_records_incomplete_without_resubmit(monkeypatch, tmp_path):
    form_screen = screen_from(catalog_xml())
    form = find_form(form_screen)
    stop = tmp_path / "STOP"
    device = SimpleNamespace(config={"app_mode": "installed"}, screens=[form_screen], driver=None,
                             stop_path=stop, deadline=time.monotonic() + 60, max_tries=30,
                             go_to=lambda screen: form_screen, observe=lambda: form_screen,
                             fresh_start=lambda: form_screen)
    session = Session(device)

    class Lost(RuntimeError):
        pass

    def boom(*args, **kwargs):
        raise Lost("invalid session id; socket hang up")

    monkeypatch.setattr(session, "perform", boom)
    assert device_unavailable(Lost("invalid session id"))
    try:
        session.attempt("Catalog form", session.form_checks, form_screen, form, area="form",
                        where=form_screen["screen_name"])
    except Lost:
        pass
    assert any(item.get("session_loss") and item.get("outcome") == "incomplete" for item in session.tried)
    assert any("no blind resubmit" in row.get("reason", "") for row in session.coverage)


def test_timeline_records_action_expected_actual_with_resource_id(tmp_path):
    timeline = Timeline(tmp_path, case={"id": "c1", "title": "Catalog"}, phase="test_build")
    step = {"action": "tap", "locator": {"strategy": "resource_id", "value": PACKAGE + ":id/countrySpinner"}}
    with timeline.action(step, 1, "catalog"):
        pass
    timeline.close()
    rows = [json.loads(line) for line in Path(tmp_path).joinpath(
        next(p.name for p in Path(tmp_path).glob("events.android-*.jsonl"))).read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "started" and rows[1]["status"] == "passed"
    assert rows[0]["expected"] and rows[1]["observed"]
    assert "resource_id:" in rows[0]["selector"]
    assert rows[0].get("locator_strategy") == "resource_id"


def test_build_form_login_still_unique_among_extra_buttons():
    buttons = [
        {"id": "a", "text": "Log in", "accessibility_id": "", "resource_id": "id/login", "password": False,
         "locators": [{"strategy": "resource_id", "value": "id/login"}]},
        {"id": "b", "text": "Continue", "accessibility_id": "", "resource_id": "id/cont", "password": False,
         "locators": [{"strategy": "resource_id", "value": "id/cont"}]},
    ]
    inputs = [{"id": "u", "text": "", "accessibility_id": "", "resource_id": "id/user", "password": False,
               "hint": "Username", "locators": [{"strategy": "resource_id", "value": "id/user"}]},
              {"id": "p", "text": "", "accessibility_id": "", "resource_id": "id/pass", "password": True,
               "hint": "Password", "locators": [{"strategy": "resource_id", "value": "id/pass"}]}]
    form = build_form(inputs, buttons)
    assert form["kind"] == "login" and form["submit"]["id"] == "a" and form["submit_status"] == "unique"
