"""Controlled pages exercise container identity, value retention and observed dialog paths."""
import re

import pytest
from playwright.sync_api import expect, sync_playwright

from backend.form_targets import fill_input_check
from backend.navigation import open_path


@pytest.fixture
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(800)
        expect.set_options(timeout=800)
        yield page
        expect.set_options(timeout=5000)
        browser.close()


def _field(name="Work Telephone", selector="input", value="9876543210", **extra):
    return {"name": name, "label": name, "selector": selector, "kind": "type", "value": value, "required": True, **extra}


def test_sidebar_search_and_duplicate_labels_are_scoped(page):
    page.set_content('''<aside><label>Search<input id=sidebar></label></aside>
      <form id=other><label>Work Telephone<input></label></form>
      <form id=business aria-label="Emergency Contact"><label>Work Telephone<input required></label></form>''')
    fill_input_check(page, {"form": "#business", "fields": [_field()]})
    assert page.locator("#sidebar").input_value() == ""
    assert page.locator("#other input").input_value() == ""
    assert page.locator("#business input").input_value() == "9876543210"


def test_unassociated_distinct_labels_resolve_within_container(page):
    page.set_content('''<form id=business><div><label>Contact Email:</label><input></div>
      <div><label>Contact Name:</label><input></div></form>''')
    fields = [_field("Contact Email:", value="qa@example.com"), _field("Contact Name:", value="QA Tester")]
    fill_input_check(page, {"form": "#business", "fields": fields})
    assert [el.input_value() for el in page.locator("input").all()] == ["qa@example.com", "QA Tester"]


@pytest.mark.parametrize("markup", [
    '<form id=business><label>Work Telephone<input></label><label>Work Telephone<input></label></form>',
    '<form id=business><input id=other></form>',
    '<form id=business><label>Work Telephone<input hidden required></label></form>',
])
def test_ambiguous_missing_and_hidden_required_targets_cannot_pass(page, markup):
    page.set_content(markup)
    field = _field(selector="#missing") if "id=other" in markup else _field()
    with pytest.raises(AssertionError):
        fill_input_check(page, {"form": "#business", "fields": [field]})


def test_wrong_retained_value_and_custom_validation_cannot_pass(page):
    page.set_content('''<form id=business><label>Work Telephone<input onblur="this.value='changed'"></label></form>''')
    with pytest.raises(AssertionError):
        fill_input_check(page, {"form": "#business", "fields": [_field()]})
    page.set_content('''<form id=business><label>Work Telephone<input onblur="this.setAttribute('aria-invalid','true')"></label></form>''')
    with pytest.raises(AssertionError, match="application validation"):
        fill_input_check(page, {"form": "#business", "fields": [_field()]})


def test_styled_checkbox_uses_its_label_and_verifies_state(page):
    page.set_content('''<form id=business><input id=consent type=checkbox style="display:none">
      <label for=consent>Contact allowed</label></form>''')
    fill_input_check(page, {"form": "#business", "fields": [_field("Contact allowed", "#consent", kind="checkbox")]})
    assert page.locator("#consent").is_checked()


def test_custom_dropdown_verifies_selected_option(page):
    page.set_content('''<form id=business><div role=combobox aria-label=Country tabindex=0 onclick="document.getElementById('options').hidden=false">Choose</div></form>
      <div id=options hidden><div role=option onclick="document.querySelector('[role=combobox]').textContent='India';document.getElementById('options').hidden=true">India</div></div>''')
    fill_input_check(page, {"form": "#business", "fields": [_field("Country", "[role=combobox]", kind="combobox", shown="India")]})
    assert page.get_by_role("combobox").inner_text() == "India"


def test_wrong_opener_cannot_establish_form_reached(page):
    page.set_content('<button id=wrong>Other</button><form id=business hidden><input></form>')
    with pytest.raises(AssertionError):
        open_path(page, [{"selector": "#wrong", "action": "click"}], "#business")


def test_login_helper_replays_recorded_modal_opener(page):
    from backend.agents.script_generator import LOGIN_HELPER
    page.set_content('''<a id=opener href="#" onclick="document.getElementById('login').hidden=false">Log in</a>
      <form id=login hidden><input id=user><input id=password type=password><button type=button id=submit>Log in</button></form>''')
    namespace = {"expect": expect, "open_path": open_path, "re": re, "_settle": lambda p: None}
    exec(LOGIN_HELPER, namespace)
    assert namespace["_sign_in"](page, {"user": "#user", "password": "#password", "submit": "#submit",
                                     "form": "#login", "openers": [{"selector": "#opener"}]}, "qa-user", "qa-password")
    assert page.locator("#user").input_value() == "qa-user"


def test_date_data_does_not_use_phone_or_generic_text():
    from backend.agents.test_design import _value_for
    assert _value_for({"type": "text", "label": "Contact Date", "placeholder": "dd/mm/yyyy"}).count("/") == 2
    assert _value_for({"type": "text", "label": "Contact Date"}) is None
    assert _value_for({"type": "number", "label": "Employee Number", "min": "1", "max": "9"}) == "9"
