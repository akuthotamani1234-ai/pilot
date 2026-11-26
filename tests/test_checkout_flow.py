"""The owner's / Jira tests go through a shop's checkout on any website - only placing the order or paying is never
done (except a demo order on a demo shop the owner confirms). Reported 26 Nov 2026: QPL-5 (checkout) and QPL-13 (cart
badge) ended 'Not automated: Not possible: ... missing' and the other checkout cases were blocked."""
import ast
import os
import re
from pathlib import Path

import pytest

from backend.atlassian.analysis import SECURITY_RULE
from backend.objective import checkout_only, destructive


def _guard(monkeypatch, mode: str, strict: bool = True) -> dict:
    """templates/conftest.py's click guard (only those parts), as an owner's test (strict = an AI-written file)."""
    from backend.actions import PROTECTED, SAFE_TEXT, WRITE
    monkeypatch.setenv("QA_PROTECTED_RX", PROTECTED.pattern)
    monkeypatch.setenv("QA_SAFE_TEXT_RX", SAFE_TEXT.pattern)
    monkeypatch.setenv("QA_WRITE_RX", WRITE.pattern)
    monkeypatch.setenv("QA_CHECKOUT_FLOW", mode)
    tree = ast.parse(Path("backend/templates/conftest.py").read_text(encoding="utf-8"))
    want = {"PROTECTED_RX", "TEST_ACCOUNT_RX", "SAFE_TEXT_RX", "UNSAFE_LINK_RX", "MONEY_RX", "WRITE_RX",
            "CONTROL_TEXT_JS", "CHECKOUT_FLOW", "CHECKOUT_WORDS", "ORDER_SUBMIT", "_checkout_open",
            "_payment_target_any", "_pay_bits", "_payment_target", "_risky", "_redirects_to_payment",
            "_refuse_protected"}
    nodes = [n for n in tree.body if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in want)
             or (isinstance(n, ast.FunctionDef) and n.name in want)]
    ns = {"re": re, "os": os, "pytest": pytest,
          "Locator": type("Locator", (), {"_qa_guard": True, "_qa_strict": strict})}
    exec(compile(ast.Module(nodes, []), "conftest.py", "exec"), ns)
    return ns


def _control(url: str, text: str, href: str = ""):
    class Loc:
        class page:
            pass

        class first:
            @staticmethod
            def evaluate(*_a, **_k):
                return [text, "", "", href, "", "button", "", "in_form", "", ""]
    Loc.page.url = url
    return Loc()


def test_an_owner_test_goes_through_the_checkout_but_never_places_the_order(monkeypatch):
    g = _guard(monkeypatch, "form")
    g["_refuse_protected"](_control("https://shop.example/cart.html", "Checkout"))  # (opens the checkout form)
    g["_refuse_protected"](_control("https://shop.example/checkout-step-one.html", "Continue"))
    g["_refuse_protected"](_control("https://shop.example/checkout", "Continue"))  # (a real /checkout page too)
    g["_refuse_protected"](_control("https://shop.example/checkout-step-two.html", "Cancel"))
    for label in ("Finish", "Place order", "Pay now", "Confirm order", "Complete purchase"):
        with pytest.raises(pytest.skip.Exception, match="places the order or pays"):
            g["_refuse_protected"](_control("https://shop.example/checkout-step-two.html", label))
    with pytest.raises(pytest.skip.Exception):  # (a payment page / provider is never opened, in any mode)
        g["_refuse_protected"](_control("https://shop.example/payment/card", "Continue"))
    with pytest.raises(pytest.skip.Exception):
        g["_refuse_protected"](_control("https://shop.example/account", "Delete account"))


def test_a_demo_shop_the_owner_confirmed_may_finish_the_demo_order(monkeypatch):
    g = _guard(monkeypatch, "demo")
    g["_refuse_protected"](_control("https://shop.example/checkout-step-two.html", "Finish"))
    with pytest.raises(pytest.skip.Exception):
        g["_refuse_protected"](_control("https://shop.example/payment/card", "Continue"))


def test_built_in_tests_keep_checkout_protected(monkeypatch):
    g = _guard(monkeypatch, "form", strict=False)  # (not an owner's / AI file: the old rule)
    with pytest.raises(pytest.skip.Exception, match="checkout or payment"):
        g["_refuse_protected"](_control("https://shop.example/checkout", "Continue"))
    assert g["_risky"](["Checkout", "", "", "", "", "button", "", "", "", ""])


@pytest.mark.parametrize("text, blocked, demo_only", [
    ("Open the cart, press Checkout and fill in the first name", "", ""),
    ("After removing it again the cart badge is not shown", "", ""),
    ("Finishing the order shows 'Thank you for your order!'", "Finishing the order", "Finishing the order"),
    ("Place an order", "Place an order", "Place an order"),
    ("Pay with a credit card", "Pay", ""),
    ("Delete the user", "Delete", ""),
])
def test_only_placing_an_order_needs_a_demo_shop_and_paying_or_deleting_stays_blocked(text, blocked, demo_only):
    assert destructive(text) == blocked
    assert checkout_only(text) == demo_only
    assert destructive(text, demo_checkout=True) == ("" if demo_only else blocked)


def test_a_badge_that_is_not_shown_is_no_security_rule():
    assert not SECURITY_RULE.search("After removing it again the cart badge is not shown")
    assert SECURITY_RULE.search("The password is never shown on the page")


def test_the_ai_is_told_that_states_reached_by_using_the_site_are_not_missing():
    from backend.agents.test_design import DEMO_CHECKOUT_RULE, NO_CHECKOUT_RULE
    from backend.llm import load_prompt
    text = load_prompt("my_tests")
    assert "NOT missing" in text and "Never answer \"Not possible\" only because a page was not crawled" in text
    assert "press Checkout" in NO_CHECKOUT_RULE and "NEVER press the button" in NO_CHECKOUT_RULE
    assert "DEMO shop" in DEMO_CHECKOUT_RULE and "NEVER type real card" in DEMO_CHECKOUT_RULE
    assert text.format(n=1, site="[]", tests="1. x", checkout_rule=NO_CHECKOUT_RULE)
