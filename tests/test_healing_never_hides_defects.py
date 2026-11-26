"""Self-healing may change HOW an element is found, never WHAT a test checks: every way a repair could turn a real
application defect into a pass is refused (both the standard healer, _safe_repair, and the evidence rewrite,
evidence_check)."""
import pytest

from backend.agents.self_healing import _safe_repair, evidence_check

OLD = '''from playwright.sync_api import expect


def test_cart(page):
    page.goto("https://shop.test/")
    page.locator("#add-1").click()
    expect(page.locator("#badge")).to_have_text("1")
    assert "Backpack" in page.locator(".cart").inner_text()


QA_EXPECTS_test_cart = ['Backpack']
'''


def _heal(old, new):
    return OLD.replace(old, new)


def test_a_new_selector_for_the_same_check_is_accepted():
    assert _safe_repair(OLD, _heal('"#add-1"', '"[data-test=add-1]"')) is None


@pytest.mark.parametrize("old,new,why", [
    ('to_have_text("1")', 'to_have_text("2")', "the expected value changed to what the broken app shows"),
    ('to_have_text("1")', 'to_be_visible()', "a value check weakened to a visibility check"),
    ('    assert "Backpack" in page.locator(".cart").inner_text()\n', "", "an assertion removed"),
    ('    expect(page.locator("#badge")).to_have_text("1")',
     '    try:\n        expect(page.locator("#badge")).to_have_text("1")\n    except AssertionError:\n        pass',
     "the failure swallowed"),
    ('"Backpack" in', '"Backpack" in "Backpack" or "x" in', "a check that cannot fail"),
    ("QA_EXPECTS_test_cart = ['Backpack']\n", "", "the quoted expected result removed"),
    ('"https://shop.test/"', '"https://shop.test/checkout/payment"', "pointed at payment"),
])
def test_a_repair_that_could_hide_a_defect_is_refused(old, new, why):
    healed = _heal(old, new)
    assert healed != OLD
    assert _safe_repair(OLD, healed), why


def test_the_evidence_rewrite_keeps_the_stated_value():
    case = {"title": "badge shows 1", "expected": "The badge shows '1'", "steps": [], "test_data": {}}
    live = {"url": "https://shop.test/cart", "texts": ["2"], "controls": []}
    healed = _heal('to_have_text("1")', 'to_have_text("2")')
    assert evidence_check(OLD, healed, "test_cart", case, live, "")
