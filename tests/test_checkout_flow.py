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
            "_refuse_protected", "CART_PAGE", "_cart_line_remove"}
    nodes = [n for n in tree.body if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in want)
             or (isinstance(n, ast.FunctionDef) and n.name in want)]
    ns = {"re": re, "os": os, "pytest": pytest,
          "Locator": type("Locator", (), {"_qa_guard": True, "_qa_strict": strict})}
    exec(compile(ast.Module(nodes, []), "conftest.py", "exec"), ns)
    return ns


def _control(url: str, text: str, href: str = "", add_buttons: int = 0):
    class Loc:
        class page:
            @staticmethod
            def get_by_role(*_a, **_k):
                return type("L", (), {"count": staticmethod(lambda: add_buttons)})()

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


def test_taking_the_item_out_of_the_tests_own_cart_is_allowed_but_remove_elsewhere_is_not(monkeypatch):
    g = _guard(monkeypatch, "form")
    g["_refuse_protected"](_control("https://shop.example/cart.html", "Remove"))
    g["_refuse_protected"](_control("https://shop.example/inventory.html", "Remove", add_buttons=6))
    with pytest.raises(pytest.skip.Exception):  # (an admin page: 'Remove' could remove a user)
        g["_refuse_protected"](_control("https://admin.example/users", "Remove"))
    g = _guard(monkeypatch, "form", strict=False)  # (built-in tests: unchanged)
    with pytest.raises(pytest.skip.Exception):
        g["_refuse_protected"](_control("https://shop.example/inventory.html", "Remove", add_buttons=6))


CASE = {"title": "Verify: After adding a product the cart badge shows 1", "tests": ["test_ai_flow_1"], "my_test": "x",
        "instruction": "Verify: After adding a product the cart badge shows 1. Expected: the cart badge shows 1.",
        "steps": ["Add a product", "Check the badge"], "expected": "the cart badge shows 1"}
OLD = '''import re
import pytest
from playwright.sync_api import expect


def test_ai_flow_1(page):
    """badge"""
    page.goto("https://shop.example/inventory.html")
    page.locator("#add").click()
    expect(page.get_by_role("button", name="Cart, empty")).to_have_text("Cart, 1 items")


def test_ai_flow_2(page):
    """other"""
    page.goto("https://shop.example/")
    expect(page.locator("h1")).to_have_text("Shop")
'''
LIVE = {"url": "https://shop.example/inventory.html", "texts": [{"text": "1", "cls": "shopping_cart_badge",
                                                                 "data_test": "shopping-cart-badge"}]}


def _new(body: str) -> str:
    return OLD.replace('''    expect(page.get_by_role("button", name="Cart, empty")).to_have_text("Cart, 1 items")''', body)


def test_an_evidence_rewrite_must_keep_the_stated_value_and_use_only_real_values():
    from backend.agents.self_healing import evidence_check as check
    good = _new('''    expect(page.locator('[data-test="shopping-cart-badge"]')).to_have_text("1")''')
    assert check(OLD, good, "test_ai_flow_1", CASE, LIVE, "") is None
    invented = _new('''    expect(page.locator('[data-test="shopping-cart-badge"]')).to_have_text("1 item added")''')
    assert "neither the test case nor the real page" in check(OLD, invented, "test_ai_flow_1", CASE, LIVE, "")
    weaker = _new('''    page.locator('[data-test="shopping-cart-badge"]').click()''')
    assert "checks less" in check(OLD, weaker, "test_ai_flow_1", CASE, LIVE, "")
    escape = _new('''    try:
        expect(page.locator('[data-test="shopping-cart-badge"]')).to_have_text("1")
    except AssertionError:
        pass''')
    assert "pass without checking" in check(OLD, escape, "test_ai_flow_1", CASE, LIVE, "")
    other = good.replace('to_have_text("Shop")', 'to_be_visible()')
    assert "only test_ai_flow_1 may be rewritten" in check(OLD, other, "test_ai_flow_1", CASE, LIVE, "")


def test_an_evidence_rewrite_never_drops_a_value_the_test_case_states():
    from backend.agents.self_healing import evidence_check as check
    case = dict(CASE, instruction="After a wrong password the page says 'Epic sadface: no match'.")
    old = OLD.replace('to_have_text("Cart, 1 items")', 'to_contain_text("Epic sadface: no match")')
    live = {"texts": [{"text": "Epic sadface: Username and password do not match"}]}
    new = old.replace('to_contain_text("Epic sadface: no match")', 'to_contain_text("Epic sadface: Username and password do not match")')
    assert "no longer checks what the test case states" in check(old, new, "test_ai_flow_1", case, live, "")


def test_an_evidence_rewrite_that_does_not_pass_is_undone_for_that_test_only(tmp_path):
    from backend.agents.self_healing import restore_function
    before, path = tmp_path / "before.py", tmp_path / "test_flows_ai.py"
    before.write_text(OLD)
    now = _new('''    expect(page.locator('[data-test="shopping-cart-badge"]')).to_have_text("1")''').replace(
        'to_have_text("Shop")', 'to_have_text("Shop!")')
    path.write_text(now)
    restore_function(path, before, "test_ai_flow_1")
    text = path.read_text()
    assert 'name="Cart, empty"' in text and 'to_have_text("Shop!")' in text  # (the other test keeps its change)


def test_a_name_the_test_types_into_a_form_is_its_own_test_data_not_an_invented_record():
    from backend.ai_grounding import grounding_problem
    pages = [{"url": "https://fixture.test/checkout", "title": "Checkout", "headings": [], "buttons": [], "forms": [], "links": [], "behaviour": [],
              "inputs": [{"selector": "#first-name", "label": "First Name"}]}]
    typed = ('def test_ai_flow_1(page):\n'
             '    page.goto("https://fixture.test/checkout")\n'
             '    page.get_by_placeholder("First Name").fill("John")\n')
    assert grounding_problem(typed, pages) is None
    clicked = typed.replace('page.get_by_placeholder("First Name").fill("John")',
                            'page.get_by_text("John Doe", exact=True).click()')
    assert grounding_problem(clicked, pages)


def test_a_test_must_check_the_result_its_test_case_quotes_or_it_cannot_pass():
    """Live 26 Nov 2026: 'Finishing the order shows "Thank you for your order!"' passed by checking only that the Finish
    button was visible - a pass that did not check the requirement."""
    from backend.agents.script_generator import quoted_expectations
    from backend.agents.self_healing import evidence_check as check
    case = dict(CASE, instruction="Verify the message 'Thank you for your order!' is shown. Steps: finish. "
                                  "Expected: Finishing the order shows 'Thank you for your order!'.",
                expected="Finishing the order shows 'Thank you for your order!'")
    assert quoted_expectations(case) == ["Thank you for your order!"]
    assert quoted_expectations(dict(case, expected="Exploratory: look at it", instruction="")) == []
    old = OLD.replace('to_have_text("Cart, 1 items")', 'to_contain_text("Thank you for your order!")')
    live = {"texts": [{"text": "Finish"}]}
    no_result = old.replace('expect(page.get_by_role("button", name="Cart, empty")).to_contain_text("Thank you for your order!")',
                            'expect(page.locator(\'[data-test="finish"]\')).to_be_visible()')
    assert "quotes" in check(old, no_result, "test_ai_flow_1", case, live, "")
