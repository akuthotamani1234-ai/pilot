"""Steps 7, 8, 9:
  * rules between fields are found from labels, names, types and choices (date range, past date, From = To, min/max,
    confirm password, count -> total, a choice that enables a box) - and a product page's quantity box next to its price
    is NOT a count -> total rule;
  * failure categories: a broken convention is a `rule_violation` (a question), a control that did nothing is
    `suspect`, another website's blocked script is `third_party` (never a blocker);
  * self-healing may change an element's address, never a check: 'or True', a changed expected value, an added
    try / except and a new skip are each rejected;
  * on TravelSite: T1 (return before departure), T2 (From = To), T3 (2 passengers = the total of 1) and T6 (a
    confirm-password mismatch) are reported as rule violations; the clean site gives none."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.travel_site import TravelSite

pytestmark = pytest.mark.slow  # (runs the whole tester: quick checks leave it out with -m "not slow")
ROOT = Path(__file__).resolve().parent.parent


def _box(sel, label, type_="text", **kw):
    return dict({"selector": sel, "label": label, "type": type_, "id": sel.strip("#"), "name": sel.strip("#")}, **kw)


def test_rules_between_fields_are_found():
    from backend.form_rules import pair_cases
    airports = [{"value": "LHR"}, {"value": "JFK"}]
    search = {"url": "https://t.test/", "slug": "home", "totals": ["Estimated total: $120"], "forms": [{
        "selector": "#search", "method": "get", "submit": {"selector": "#go", "text": "Search"},
        "fields": [_box("#from", "From", "select-one", tag="select", options=airports),
                   _box("#to", "To", "select-one", tag="select", options=airports),
                   _box("#depart", "Departure date", "date"), _box("#return", "Return date", "date"),
                   _box("#pax", "Passengers", "number")]}], "inputs": [], "buttons": []}
    signup = {"url": "https://t.test/signup", "slug": "signup", "forms": [{
        "selector": "#signup", "method": "post", "submit": {"selector": "#create", "text": "Create account"},
        "fields": [_box("#mail", "E-mail", "email"), _box("#pw", "Password", "password"),
                   _box("#pw2", "Confirm password", "password")]}], "inputs": [], "buttons": []}
    product = {"url": "https://t.test/item/1", "slug": "item", "forms": [{
        "selector": "#buy", "method": "post", "submit": {"selector": "#add", "text": "Add to cart"},
        "fields": [_box("#qty", "Quantity", "number"), _box("#size", "Size", "select-one", tag="select",
                                                           options=[{"value": "S"}, {"value": "M"}])]}],
               "inputs": [], "buttons": []}  # (no total shown: the quantity box is no count -> total rule)
    rules = {(c["spec"]["rule"], c["spec"]["a_name"], c["spec"]["b_name"]) for c in pair_cases([search, signup, product])}
    assert ("date_range", "Departure date", "Return date") in rules
    assert ("past_date", "Departure date", "Departure date") in rules
    assert ("same_value", "From", "To") in rules
    assert ("count_total", "Passengers", "Passengers") in rules
    assert ("confirm", "Password", "Confirm password") in rules
    assert not [r for r in rules if r[1] == "Quantity"]


def test_the_new_failure_categories(tmp_path):
    from backend.agents.failure_analysis import classify, failure_analysis_agent
    rule = {"outcome": "failed", "error_type": "AssertionError", "file": "test_field_rules.py", "test": "test_pair_1",
            "error": "E   AssertionError: [rule] The site accepted 'Return date' before 'Departure date'. Is that allowed?"}
    assert classify(rule)[0] == "rule_violation" and "Is that allowed?" in classify(rule)[1]
    nothing = {"outcome": "failed", "error_type": "AssertionError", "file": "test_learned.py", "test": "test_learned_1",
               "error": "AssertionError: 'Load totals' gave no visible response (no message, nothing changed)"}
    assert classify(nothing)[0] == "suspect"
    out = failure_analysis_agent({"url": "https://shop.test/", "results": [], "run_dir": str(tmp_path), "crawl_issues": [
        {"type": "failed_request", "url": "https://shop.test/", "page": "home",
         "detail": "net::ERR_BLOCKED_BY_ORB → https://cdn.tracker.example/a.js"},
        {"type": "failed_request", "url": "https://shop.test/", "page": "home", "detail": "HTTP 500 → https://shop.test/api"}]})
    cats = {f["error"].split("→")[-1].strip(): (f["category"], f["severity"]) for f in out["failures"]}
    assert cats["https://cdn.tracker.example/a.js"] == ("third_party", "low")
    assert cats["https://shop.test/api"][0] == "product_defect"  # (the website's own request stays its problem)


OLD = '''def test_x(page):
    page.locator("#old").click()
    expect(page.locator("#total")).to_have_text("Total: 4560")
    assert page.url.endswith("/done"), "not done"
'''


def test_healing_may_change_an_address_never_a_check():
    from backend.agents.self_healing import _checks_unchanged
    assert _checks_unchanged(OLD, OLD.replace("#old", "#new").replace('locator("#total")', 'locator("#sum")')) is None
    assert _checks_unchanged(OLD, OLD.replace('"not done"', '"not done"').replace(
        'endswith("/done")', 'endswith("/done") or True')) is not None
    assert _checks_unchanged(OLD, OLD.replace("Total: 4560", "Total: 0")) is not None          # another expected value
    wrapped = OLD.replace('    expect(page.locator("#total")).to_have_text("Total: 4560")\n',
                          '    try:\n        expect(page.locator("#total")).to_have_text("Total: 4560")\n'
                          '    except AssertionError:\n        pass\n')
    assert _checks_unchanged(OLD, wrapped) is not None                                          # a new try / except
    assert _checks_unchanged(OLD, OLD.replace('    page.locator("#old").click()\n',
                                              '    pytest.skip("later")\n')) is not None          # a new skip
    assert _checks_unchanged(OLD, OLD + "    assert True\n") is not None                         # a constant


def _run(site, tmp_path, path):
    env = os.environ.copy()
    env.update({"LLM_PROVIDER": "none", "HEADLESS": "true", "SLOW_MO_MS": "0", "TEST_WORKERS": "2",
                "RUNS_DIR": str(tmp_path / "runs"), "BASELINE_DIR": str(tmp_path / "baseline"),
                "WORKSPACE_DIR": str(tmp_path / "ws"), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                "PATTERN_SAMPLES": "2"})
    r = subprocess.run([sys.executable, "main.py", site.url + path, "--no-open"], check=False, cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    run = sorted((tmp_path / "runs").iterdir())[-1]
    return json.loads((run / "failures.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("bugs", [False, True])
def test_travel_rules_are_questions_when_broken(tmp_path, bugs):
    site = TravelSite(bugs=bugs).start()
    try:
        failures = _run(site, tmp_path, "/")
    finally:
        site.stop()
    rules = [f for f in failures if f["category"] == "rule_violation"]
    text = " ".join(f["explanation"] for f in rules)
    if not bugs:
        assert rules == [], text
        return
    assert "'Return date' before 'Departure date'" in text        # T1
    assert "the same value in 'From' and 'To'" in text            # T2
    assert "Changing 'Passengers'" in text                        # T3
    assert "'Confirm password' that differs" in text              # T6
