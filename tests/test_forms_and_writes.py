"""Steps 4 + 5 - what a run may change, and forms checked like a tester:
  * the action classes per environment (production / test never change data; staging sends forms; delete / logout /
    password / pay only when allowed), and the second confirmation for a host that does not look like a test copy;
  * field-aware test values (card numbers that pass / fail the Luhn check, MM/YY, e-mails, amounts ...);
  * staging on AdminPortal: create -> find -> edit -> delete passes on the clean portal, fails on its planted bug
    (B7: the edited name is not saved); everything created is in created.json and nothing tagged is left;
  * production on AdminPortal: the e-mail box is tested WITHOUT sending - the planted bug (B3: 'a@' is accepted and
    sent) is caught - and the portal receives 0 POSTs."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.config import settings
from tests.admin_portal import AdminPortal

pytestmark = pytest.mark.slow  # (runs the whole tester: quick checks leave it out with -m "not slow")
ROOT = Path(__file__).resolve().parent.parent


def test_what_each_environment_may_do(monkeypatch):
    from backend.actions import action_class, action_risk, protected_pattern
    assert action_class("Save changes") == "write" and action_class("Delete") == "delete"
    assert action_class("Pay now") == "pay" and action_class("Log out") == "logout"
    assert action_class("Add to cart") == "test_account" and action_class("Search") == "safe"
    for env in ("production", "test"):  # (test is the default: a website tested without choosing stays untouched)
        monkeypatch.setattr(settings, "environment", env)
        assert action_risk("Save changes") == "protected" and action_risk("Delete") == "protected"
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "writes_ok", True)
    monkeypatch.setattr(settings, "allow_actions", [])
    monkeypatch.setattr(settings, "test_payment", False)
    assert action_risk("Save changes") == "write" and action_risk("Submit") == "write"
    assert action_risk("Delete") == "protected" and action_risk("Pay now") == "protected"
    monkeypatch.setattr(settings, "allow_actions", ["delete", "pay"])
    assert action_risk("Delete") == "write"
    assert action_risk("Pay now") == "protected"  # pay also needs the payment provider's test mode
    monkeypatch.setattr(settings, "test_payment", True)
    assert action_risk("Pay now") == "write"
    import re
    assert not re.search(protected_pattern(), "Delete", re.I) and re.search(protected_pattern(), "Log out", re.I)
    monkeypatch.setattr(settings, "writes_ok", False)  # staging on a real-looking host without the 2nd confirmation
    assert action_risk("Save changes") == "protected"


def test_a_host_that_does_not_look_like_a_test_copy_needs_the_second_confirmation():
    from backend.safety import looks_like_test_host
    for host in ("staging.shop.com", "shop-test.example.com", "qa.portal.io", "dev.app.net", "uat-bank.com",
                 "preview.site.dev", "localhost", "127.0.0.1"):
        assert looks_like_test_host(host), host
    for host in ("shop.com", "www.bank.com", "automationteststore.com"):
        assert not looks_like_test_host(host), host


def test_values_fit_the_box():
    from backend.testdata import field_kind, luhn_ok, values
    assert field_kind({"type": "text", "placeholder": "1234 5678 9012 3456"}) == "card_number"
    assert field_kind({"type": "text", "placeholder": "MM/YY"}) == "card_expiry"
    assert field_kind({"type": "text", "label": "CVV"}) == "cvv"
    assert field_kind({"type": "text", "autocomplete": "cc-number"}) == "card_number"
    assert field_kind({"type": "email"}) == "email" and field_kind({"type": "text", "label": "E-mail"}) == "email"
    assert field_kind({"type": "number", "label": "Amount"}) == "amount"
    assert field_kind({"type": "checkbox"}) == "" and field_kind({"tag": "select"}) == ""
    assert luhn_ok("4111 1111 1111 1111") and not luhn_ok("4111 1111 1111 1112")
    card = {v["value"]: v["expect"] for v in values({"type": "text", "label": "Card number"})}
    assert card["4111 1111 1111 1111"] == "accept" and card["4111 1111 1111 1112"] == "reject"
    expiry = {v["value"]: v["expect"] for v in values({"type": "text", "placeholder": "MM/YY"})}
    assert expiry == {"12/30": "accept", "13/30": "reject"}
    mail = {v["value"]: v["expect"] for v in values({"type": "email", "required": True})}
    assert mail["qa.tester@example.com"] == "accept" and mail["a@"] == "reject" and mail[""] == "reject"
    amount = {v["value"]: v["expect"] for v in values({"type": "text", "label": "Amount"})}
    assert amount["0"] == "either" and amount["-1"] == "reject"
    age = {v["value"]: v["expect"] for v in values({"type": "number", "label": "Age", "min": "18", "max": "99"})}
    assert age["18"] == "accept" and age["17"] == "reject" and age["99"] == "accept" and age["100"] == "reject"


def _run(portal, tmp_path, path, **env_extra):
    env = os.environ.copy()
    env.update({"LLM_PROVIDER": "none", "HEADLESS": "true", "SLOW_MO_MS": "0", "TEST_WORKERS": "2",
                "RUNS_DIR": str(tmp_path / "runs"), "BASELINE_DIR": str(tmp_path / "baseline"),
                "WORKSPACE_DIR": str(tmp_path / "ws"), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
                "MAX_INTERACTIONS_PER_PAGE": "6", "PATTERN_SAMPLES": "1", **env_extra})
    r = subprocess.run([sys.executable, "main.py", portal.url + path, "--no-open"], check=False, cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    run = sorted((tmp_path / "runs").iterdir())[-1]
    return json.loads((run / "test_cases.json").read_text(encoding="utf-8")), run, r.stdout


@pytest.mark.parametrize("bugs", [False, True])
def test_staging_creates_finds_edits_and_deletes_and_cleans_up(tmp_path, bugs):
    portal = AdminPortal(bugs=bugs).start()
    try:
        # (REVIEW=off: on staging the run asks its questions and waits 15 min for an answer nobody gives here - the
        # review has its own tests; this one is about the data a staging run creates and cleans up)
        cases, run, out = _run(portal, tmp_path, "/users", TEST_ENVIRONMENT="staging", ALLOW_ACTIONS="delete",
                               REVIEW="off")
        left = portal.tagged()
    finally:
        portal.stop()
    assert "Staging: forms are sent" in out
    crud = [c for c in cases if c.get("kind") == "crud"]
    assert crud, [c["title"] for c in cases]
    if bugs:  # B7: the edited name is not saved -> the round trip fails at that step
        assert crud[0]["execution_status"] == "Failed", crud[0].get("actual_result")
        assert "edited name" in (crud[0].get("actual_result") or "") + json.dumps(crud[0].get("evidence"))
    else:
        assert crud[0]["execution_status"] == "Passed", crud[0].get("actual_result")
    created = json.loads((run / "created.json").read_text(encoding="utf-8"))
    assert created["created"] >= 1
    assert left == [], left  # nothing tagged with the run is left on the portal (deleted by its test or the cleanup)
    s = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert s["data_created"]["left"] == 0


@pytest.mark.parametrize("bugs", [False, True])
def test_production_checks_the_form_without_sending_anything(tmp_path, bugs):
    portal = AdminPortal(bugs=bugs).start()
    try:
        cases, run, out = _run(portal, tmp_path, "/users/new", TEST_ENVIRONMENT="production")
        posts = list(portal.posts)
    finally:
        portal.stop()
    assert posts == [], posts  # the write guard stopped every POST: nothing reached the website
    wrong_mail = [c for c in cases if c.get("kind") == "form" and "wrong values in 'E-mail'" in c["title"]]
    valid = [c for c in cases if c.get("kind") == "form" and "valid values are accepted" in c["title"]]
    assert wrong_mail and valid, [c["title"] for c in cases]
    assert valid[0]["execution_status"] == "Passed"  # the page TRIED to send the valid values ("would send")
    if bugs:  # B3: 'a@' is accepted and sent ('qa.tester' is refused - so the form does check this box)
        assert wrong_mail[0]["execution_status"] == "Failed", wrong_mail[0].get("actual_result")
        assert "'a@'" in (wrong_mail[0].get("actual_result") or "")
    else:
        assert wrong_mail[0]["execution_status"] == "Passed", wrong_mail[0].get("actual_result")
