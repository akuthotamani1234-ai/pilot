"""Forms filled like a tester (live OrangeHRM run, 2026-11-22: only 2 of 10 form checks passed).

What went wrong there, and what is checked here on a page built like OrangeHRM's forms:
  * the label sits in a wrapper beside the box (not linked with for=): the box was named by its placeholder
    ('Type for hints...') and four boxes shared one name;
  * the address used a class that changes when the box is clicked (oxd-input--active -> --focus): after typing,
    the address pointed to ANOTHER box ('it should keep the typed text' failed 9 times);
  * every text box got 'QA Tester' - also 'Driver's License Number', 'Other Id', 'Street 2';
  * a 'type, then pick' box refuses typed text ('Invalid') until one of its suggestions is picked;
  * a custom '-- Select --' dropdown is a <div>, not a <select>;
  * the result table is built of <div role=table>: it was not recorded, so no test could check its rows."""
import re

import pytest
from playwright.sync_api import expect, sync_playwright

from backend.agents.discovery import EXTRACT_JS
from backend.testdata import field_kind, valid_value

HTML = """<!doctype html><title>OrangeHRM</title>
<aside><input placeholder="Search"></aside>
<form class="oxd-form" novalidate>
 <div class="oxd-input-group"><div class="lw"><label class="oxd-label">Employee Name</label></div>
  <div class="oxd-autocomplete-wrapper"><div class="oxd-autocomplete-text-input"><input placeholder="Type for hints...">
  </div><div role="listbox" id="lb"></div></div></div>
 <div class="oxd-input-group"><div class="lw"><label class="oxd-label">Supervisor Name</label></div>
  <div class="oxd-autocomplete-text-input"><input placeholder="Type for hints..."></div></div>
 <div class="oxd-input-group"><div class="lw"><label class="oxd-label">Employee Id</label></div>
  <div><input class="oxd-input oxd-input--active"></div></div>
 <div class="oxd-input-group"><div class="lw"><label class="oxd-label">Other Id</label></div>
  <div><input class="oxd-input oxd-input--active"></div></div>
 <div class="oxd-input-group"><div class="lw"><label class="oxd-label">License Expiry Date</label></div>
  <div><input class="oxd-input oxd-input--active" placeholder="yyyy-dd-mm"></div></div>
 <div class="oxd-input-group"><div class="lw"><label class="oxd-label">Employment Status</label></div>
  <div class="oxd-select-wrapper"><div class="oxd-select-text oxd-select-text--active" tabindex="0">-- Select --</div>
  </div></div>
 <button type="submit">Search</button>
</form>
<div class="oxd-table" role="table">
 <div role="rowgroup"><div role="row"><div role="columnheader">Id</div><div role="columnheader">Name</div></div></div>
 <div role="rowgroup">
  <div role="row"><div role="cell">0295</div><div role="cell">Linda Anderson</div></div>
  <div role="row"><div role="cell">0312</div><div role="cell">Peter Mac</div></div></div></div>
<script>
document.querySelectorAll('input.oxd-input').forEach(i => {
  i.addEventListener('focus', () => { i.classList.replace('oxd-input--active', 'oxd-input--focus'); });
  i.addEventListener('blur', () => { i.classList.replace('oxd-input--focus', 'oxd-input--active'); });
});
const names = ['Linda Anderson', 'Peter Mac Anderson', 'Anne Smith'];
document.querySelectorAll('.oxd-autocomplete-text-input input').forEach(inp => inp.addEventListener('input', () => {
  const lb = document.getElementById('lb');
  lb.innerHTML = '<div role="option">Searching....</div>';
  setTimeout(() => {
    lb.innerHTML = '';
    names.filter(n => n.toLowerCase().includes(inp.value.toLowerCase())).forEach(n => {
      const o = document.createElement('div'); o.setAttribute('role', 'option'); o.textContent = n;
      o.onclick = () => { inp.value = n; inp.dataset.picked = n; lb.innerHTML = ''; };
      lb.appendChild(o);
    });
  }, 500);
}));
const st = document.querySelector('.oxd-select-text');
st.onclick = () => {
  const l = document.createElement('div'); l.setAttribute('role', 'listbox');
  ['-- Select --', 'Full-Time Permanent', 'Part-Time'].forEach(t => {
    const o = document.createElement('div'); o.setAttribute('role', 'option'); o.textContent = t;
    o.onclick = () => { st.textContent = t; l.remove(); }; l.appendChild(o);
  });
  st.parentElement.appendChild(l);
};
</script>"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.route("https://fixture.test/**", lambda r: r.fulfill(content_type="text/html", body=HTML))
    pg.goto("https://fixture.test/")
    yield pg
    ctx.close()


def test_each_box_gets_a_value_that_fits_it():
    cases = {"Employee Id": ("identifier", "QA12345"), "Other Id": ("identifier", "QA12345"),
             "Driver's License Number": ("identifier", "QA12345"), "Street 2": ("address", "12 Test Street"),
             "Username": ("username", "qa.tester01"), "Email": ("email", "qa.tester@example.com")}
    for label, (kind, value) in cases.items():
        assert (field_kind({"label": label}), valid_value({"label": label})) == (kind, value), label
    # a date box takes the date in the order its placeholder shows - also OrangeHRM's yyyy-dd-mm
    box = {"label": "License Expiry Date", "placeholder": "yyyy-dd-mm"}
    assert field_kind(box) == "date"  # (not a card's expiry date)
    assert re.fullmatch(r"\d{4}-(\d{2})-(\d{2})", valid_value(box))
    y, d, m = valid_value(box).split("-")
    assert 1 <= int(m) <= 12 and 1 <= int(d) <= 31
    assert valid_value({"label": "Date of Birth", "placeholder": "dd/mm/yyyy"}) == "15/06/1995"


def test_boxes_are_named_by_their_label_and_found_by_a_stable_address(page):
    data = page.evaluate(EXTRACT_JS)
    boxes = {i["label"]: i for i in data["inputs"]}
    for label in ("Employee Name", "Supervisor Name", "Employee Id", "Other Id", "License Expiry Date"):
        assert label in boxes, list(boxes)
    assert "Type for hints..." not in boxes
    assert boxes["Employee Name"]["suggests"] and boxes["Supervisor Name"]["suggests"]
    assert not boxes["Employee Id"]["suggests"]
    for label in ("Employee Id", "Other Id", "Employee Name", "Supervisor Name"):
        sel = boxes[label]["selector"]
        assert "--active" not in sel and "--focus" not in sel, sel
        assert page.locator(sel).count() == 1, (label, sel)
    # the address still points to the SAME box after it is clicked (its class changes) - and keeps the typed text
    box = page.locator(boxes["Other Id"]["selector"])
    box.fill("QA12345")
    expect(page.locator(boxes["Other Id"]["selector"])).to_have_value("QA12345")
    expect(page.locator(boxes["Employee Id"]["selector"])).to_have_value("")


def test_a_table_of_divs_is_recorded_with_its_rows_and_real_values(page):
    data = page.evaluate(EXTRACT_JS)
    assert len(data["tables"]) == 1, data["tables"]
    t = data["tables"][0]
    assert t["role"] == "table" and t["columns"] == ["Id", "Name"] and t["rows"] == 2
    assert t["sample_rows"][0] == ["0295", "Linda Anderson"]
    assert page.locator(f"{t['selector']} {t['row_selector']}").count() == 2
    assert page.locator(f"{t['selector']} {t['row_selector']}").first.locator(t["cell_selector"]).count() == 2
    # the AI's code may use these rows now: they were observed
    from backend.ai_grounding import grounding_problem
    code = ("from playwright.sync_api import expect\n\n\ndef test_x(page):\n"
            f"    rows = page.locator({(t['selector'] + ' ' + t['row_selector'])!r})\n"
            "    expect(rows.first).to_contain_text('Linda Anderson')\n")
    assert grounding_problem(code, [dict(data, url="https://fixture.test/")]) is None


def _helpers() -> dict:
    from backend.forms import FORM_HELPERS
    steps: list[str] = []
    ns = {"re": re, "expect": expect, "pytest": pytest, "_step_ok": steps.append, "_steps": steps}
    exec(compile(FORM_HELPERS, "form_helpers", "exec"), ns)  # (the generated tests' own helpers)
    return ns


def test_a_type_then_pick_box_gets_one_of_the_websites_own_suggestions(page):
    ns = _helpers()
    box = page.locator("xpath=//label[normalize-space(.)='Employee Name']/ancestor::*[2]//input")
    picked = ns["_pick_suggestion"](page, box, {"name": "Employee Name"})
    assert picked == "Linda Anderson"  # (a record the website showed - never an invented name)
    assert box.input_value() == "Linda Anderson" and box.get_attribute("data-picked") == "Linda Anderson"
    assert any("picked 'Linda Anderson'" in s for s in ns["_steps"])


def test_a_custom_dropdown_gets_its_first_real_option(page):
    ns = _helpers()
    assert ns["_pick_custom_choices"](page, page.locator("form")) == ["Full-Time Permanent"]
    expect(page.locator(".oxd-select-text")).to_have_text("Full-Time Permanent")


def test_values_are_realistic_new_every_run_and_in_the_websites_format(page):
    from backend.testdata import observed_values, real_value
    a, b = real_value("names", "qa-111-01"), real_value("names", "qa-222-01")
    assert re.fullmatch(r"[A-Z][a-z]+ [A-Z][a-z]+", a) and a != b  # (a person's name, another one next run)
    assert real_value("names", "qa-111-01") == a  # (the same run: the same value - it can be checked again)
    assert real_value("names", "qa-111-01", keep=True).endswith("qa-111-01")  # (a saved record keeps its tag)
    assert re.fullmatch(r"[a-z]+\.[a-z]+\d{4}@example\.com", real_value("email", "qa-111-01"))
    # an ID in the website's own format, never one it already shows
    data = page.evaluate(EXTRACT_JS)
    seen = observed_values([data], {"label": "Employee Id"})
    assert seen == ["0295", "0312"]
    for tag in ("qa-1", "qa-2", "qa-3"):
        value = real_value("identifier", tag, seen)
        assert re.fullmatch(r"\d{4}", value) and value not in seen, value
    assert re.fullmatch(r"EMP-\d{4}", real_value("identifier", "qa-1", ["EMP-0042", "EMP-0007"]))
    assert observed_values([data], {"label": "Employee Name"}) == ["Linda Anderson", "Peter Mac"]
    assert observed_values([data], {"label": "Comment"}) == []
