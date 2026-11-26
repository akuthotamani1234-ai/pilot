"""Selector recovery (ai_grounding.snap_selectors) may only replace an invented selector by the ONE real control the
same identifying value names - it must never change what the test does: no compound selectors, no partial matches,
no class (a group) swapped for an id (one control), no swap when two controls share the value, and the action and
the checked value stay exactly as the AI wrote them."""
from backend.ai_grounding import snap_selectors

PAGES = [{"buttons": [{"selector": '[data-test="add-to-cart-sauce-labs-backpack"]', "text": "Add to cart"},
                      {"selector": '[data-test="remove-sauce-labs-backpack"]', "text": "Remove"},
                      {"selector": "#checkout", "text": "Checkout"},
                      {"selector": '[data-test="continue"]', "text": "Continue"},
                      {"selector": "#continue", "text": "Continue shopping"}],
          "links": [{"selector": '[data-test="shopping-cart-link"]', "text": ""},
                    {"selector": ".cart-total", "text": "Total"}]}]


def _snap(sel, action="click()"):
    return snap_selectors(f"def test_x(page):\n    page.locator({sel!r}).{action}\n", PAGES)


def test_a_test_id_written_with_the_wrong_attribute_is_the_same_control():
    code, swaps = _snap('[data-testid="shopping-cart-link"]')
    assert swaps == [('[data-testid="shopping-cart-link"]', '[data-test="shopping-cart-link"]')]
    assert ".click()" in code  # (the action is unchanged)


def test_the_value_must_be_exactly_the_same_never_a_similar_control():
    assert _snap('[data-test="add-to-cart-backpack"]')[1] == []  # (not the closest: the same, or nothing)
    assert _snap('[data-test="remove-sauce-labs-bike-light"]')[1] == []


def test_partial_matches_compound_selectors_and_group_vs_one_are_never_swapped():
    assert _snap('[class*="cart-total"]')[1] == []  # (partial match)
    assert _snap('#cart-total')[1] == []  # (one control by id vs a class = a group)
    assert _snap('.checkout')[1] == []  # (a class vs the id of one control)
    assert _snap('#item_4_title_link + .cart-total')[1] == []  # (compound: means a position)
    assert _snap('form .cart-total, #x')[1] == []


def test_two_real_controls_with_the_value_means_no_swap():
    assert _snap('[data-qa="continue"]')[1] == []  # ('continue' names the Continue button AND Continue shopping)


def test_checked_texts_and_values_are_never_touched():
    code, swaps = snap_selectors("def test_x(page):\n    expect(page.locator('[data-testid=\"shopping-cart-link\"]'))"
                                 ".to_have_text('1')\n    page.fill('#zip', '12345')\n", PAGES)
    assert ".to_have_text('1')" in code and "'12345'" in code and "'#zip'" in code  # (#zip: no real control)
    assert len(swaps) == 1
