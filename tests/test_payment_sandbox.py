"""Phase 5: checkout, payment sandbox and order lifecycle - paying only in a declared provider sandbox with its
official test instruments, never a real card; a paying case without a sandbox is Blocked with what it needs (never
silently dropped); an order status that changes later is awaited for a bounded time and reported as awaiting an
external event, never invented. (Live payment validation is BLOCKED: no application with a payment sandbox here.)"""
import ast
import json
import os
import re
from pathlib import Path

import pytest

from backend import payment_sandbox as ps
from backend.atlassian import bridge
from backend.objective import destructive, needs_payment_sandbox
from tests.test_requirements_execution import _accept, api  # noqa: F401


def test_paying_needs_a_sandbox_and_deleting_or_transferring_never_runs():
    assert needs_payment_sandbox("Pay with a card and see the order confirmation") == "Pay"
    assert destructive("Pay with a card", demo_checkout=True, payment_sandbox=True) == ""
    assert destructive("Delete the user", payment_sandbox=True) == "Delete"
    assert destructive("Transfer money to another account", payment_sandbox=True) == "Transfer"
    assert needs_payment_sandbox("Pay, then delete the account") == ""  # (a sandbox cannot make deleting safe)


def test_the_catalog_holds_official_test_instruments_and_names_them_for_the_ai():
    assert ps.allowed_card("4242 4242 4242 4242", "stripe") and not ps.allowed_card("5555555555554444", "stripe")
    assert ps.test_cards("paypal") == {} and "sandbox buyer account" in ps.provider("paypal")["details"]
    rule = ps.prompt_rule("stripe")
    assert "4242424242424242 (succeeds)" in rule and "Never type any other card number" in rule
    assert ps.prompt_rule("unknown") == ""


def _guard(monkeypatch, cards="", flow="form", hosts="", strict=True):
    monkeypatch.setenv("QA_SANDBOX_CARDS", cards)
    monkeypatch.setenv("QA_CHECKOUT_FLOW", flow)
    monkeypatch.setenv("QA_SANDBOX_HOSTS", hosts)
    tree = ast.parse(Path("backend/templates/conftest.py").read_text(encoding="utf-8"))
    want = {"SANDBOX_CARDS", "PUBLIC_TEST_CARDS", "CARD_LIKE", "_luhn", "_refuse_card", "CHECKOUT_FLOW", "SANDBOX_HOSTS", "_checkout_open",
            "_pay_bits", "_payment_target"}
    nodes = [n for n in tree.body if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in want)
             or (isinstance(n, ast.FunctionDef) and n.name in want)]
    from urllib.parse import unquote, urlparse  # noqa: F401
    ns = {"re": re, "os": os, "pytest": pytest, "urlparse": urlparse,
          "Locator": type("Locator", (), {"_qa_strict": strict})}
    exec(compile(ast.Module(nodes, []), "conftest.py", "exec"), ns)
    return ns


def test_a_test_can_never_type_a_number_that_could_be_a_real_card(monkeypatch):
    g = _guard(monkeypatch)
    real_looking = "4012 8888 8888 1881"  # (passes the checksum, not a published test number of this catalog)
    with pytest.raises(pytest.skip.Exception, match="looks like a real card number"):
        g["_refuse_card"](real_looking)
    for ok in ("4111 1111 1111 1111", "4242424242424242",  # (published test numbers: validation checks)
               "4111 1111 1111 1112", "99999999999999999999",  # (fails the checksum / too long: no card)
               "Jane", "12345"):
        g["_refuse_card"](ok)
    g = _guard(monkeypatch, cards="4012888888881881")  # (a sandbox that lists it as its test number)
    g["_refuse_card"](real_looking)


def test_in_a_sandbox_only_that_providers_pages_open_and_a_live_payment_page_stays_closed(monkeypatch):
    g = _guard(monkeypatch, flow="sandbox", hosts="www.sandbox.paypal.com")
    assert not g["_payment_target"]("https://www.sandbox.paypal.com/checkoutnow?token=x")
    assert not g["_payment_target"]("https://shop.example/checkout/payment")  # (the app's own pages)
    assert g["_payment_target"]("https://www.paypal.com/checkoutnow?token=x")  # (live PayPal)
    g = _guard(monkeypatch, flow="form")
    assert g["_payment_target"]("https://www.sandbox.paypal.com/checkoutnow")  # (no sandbox declared: protected)


def _case(cid, text):
    return {"id": cid, "tenant_id": "t", "requirement_id": "A", "status": "approved", "fingerprint": cid,
            "version": 1, "kind": "positive", "title": text, "preconditions": [], "steps": [text],
            "expected": "the order is confirmed", "assertions": [], "test_data_needs": [], "source_key": "jira:A",
            "source_version": 1, "criterion_ids": ["A#AC-1"], "payment_sandbox": needs_payment_sandbox(text)}


def test_a_paying_case_without_a_sandbox_is_blocked_with_what_it_needs_and_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "refresh", lambda *a, **k: None)
    db = bridge.connect(tmp_path / "req.db")
    bridge._save(db, "t", _case("TC-A-1", "Pay with a card"), "test")
    bridge._save(db, "t", _case("TC-A-2", "Open the order history"), "test")
    ex = bridge.plan(db, "t", ["TC-A-1", "TC-A-2"], "requirements", {"url": "https://shop.example/"})["execution"]
    assert ex["case_ids"] == ["TC-A-2"] and "payment sandbox" in ex["excluded"][0]["reason"]
    run = tmp_path / "run"
    run.mkdir()
    (run / "test_cases.json").write_text(json.dumps([{"requirement_test": "TC-A-2", "execution_status": "Passed"}]))
    done = bridge.collect(db, "t", ex["id"], run)
    res = {r["test_case_id"]: r for r in bridge.results(db, "t", ex["id"])}
    assert res["TC-A-1"]["status"] == "Blocked" and "official test instruments" in res["TC-A-1"]["reason"]
    assert bridge.outcome_of(done)["tally"]["selected"] == 2 and bridge.outcome_of(done)["tally"]["blocked"] == 1
    with_sandbox = bridge.plan(db, "t", ["TC-A-1"], "requirements",
                               {"url": "https://shop.example/", "payment_provider": "stripe"})["execution"]
    assert with_sandbox["case_ids"] == ["TC-A-1"] and not with_sandbox["excluded"]


def test_the_sandbox_must_be_confirmed_and_then_the_run_pays_only_there(api, monkeypatch):
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    launched = []
    monkeypatch.setattr(api.server, "_launch_run", lambda req, caller: launched.append(req) or {"id": 31})
    body = {"strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1"]},
            "target": {"url": "https://shop.example/", "authorized": True, "test_username": "u",
                       "test_password": "p", "payment_provider": "stripe"}}
    pre = api.client.post("/api/requirements/executions/preflight", headers=api.H, json=body).json()
    assert any(p["code"] == "payment" and p["recovery"] == "confirm_payment" for p in pre["problems"])
    body["target"]["payment_sandbox_confirmed"] = True
    r = api.client.post("/api/requirements/executions", headers=api.H, json=body)
    assert r.status_code == 200, r.text
    req = launched[0]
    assert req.environment == "staging" and req.test_payment and req.allow_actions == "pay"
    assert req.payment_sandbox == "stripe" and req.writes_confirmed


def test_an_order_status_that_never_comes_is_awaiting_an_external_event_not_a_result(capsys):
    from backend.agents.script_generator import AWAIT_HELPER, _with_said
    ns: dict = {}
    exec(AWAIT_HELPER, ns)

    class Loc:
        def __init__(self, texts):
            self.texts = list(texts)

        def inner_text(self, timeout=0):
            return self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]

    class Page:
        reloads = 0

        def wait_for_timeout(self, ms):
            pass

        def reload(self):
            Page.reloads += 1
    assert ns["_await_status"](Page(), Loc(["Processing", "Shipped"]), "Shipped", timeout_s=5, every_s=0) == "Shipped"
    shown = ns["_await_status"](Page(), Loc(["Processing"]), "Delivered", timeout_s=0, every_s=0)
    assert shown == "Processing" and "[qa-inconclusive] awaiting an external event" in capsys.readouterr().out
    code = "import re\nfrom playwright.sync_api import expect\n\ndef test_x(page):\n    _await_status(page, page.locator('#s'), 'Shipped')\n"
    assert "def _await_status" in _with_said(code)
