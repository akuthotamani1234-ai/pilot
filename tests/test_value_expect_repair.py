"""TC-QPL-4-1 (Phase 1 live run): the AI wrote `name = loc.inner_text(); expect(name).to_contain("x")`, which Playwright
refuses (ValueError: Unsupported type <str>), so a correct cart failed for a coding mistake. The repair rewrites such a
check into the equivalent assert: the check is still evaluated (it fails when the value is wrong), never dropped."""
import ast

import pytest

from backend.agents.script_generator import fix_value_expects

CODE = '''def test_cart(page):
    item_name = page.locator('[data-test="inventory-item-name"]').inner_text()
    price = page.locator('.price').text_content()
    rows = page.locator('.row').count()
    expect(item_name).to_contain("Sauce Labs Backpack")
    expect(price).to_have_text("$29.99")
    expect(rows).to_have_count(1)
    expect(item_name).not_to_contain("Bike Light")
    expect(page.locator('.cart')).to_contain_text("Backpack")
'''


def _run(code, **values):
    fn = {}
    tree = ast.parse(code)
    body = [n for n in tree.body[0].body if not isinstance(n, ast.Assign)]
    mod = ast.Module(body=[ast.FunctionDef(name="t", args=tree.body[0].args, body=body, decorator_list=[],
                                           returns=None, type_params=[])], type_ignores=[])
    ast.fix_missing_locations(mod)

    class Expect:
        def __init__(self, x):
            pass

        def __getattr__(self, k):
            return lambda *a, **kw: None
    exec(compile(mod, "t", "exec"), {"expect": Expect, **values}, fn)
    return fn["t"]


def test_checks_on_values_become_equivalent_asserts_and_locator_checks_stay():
    code, fixes = fix_value_expects(CODE)
    assert len(fixes) == 4
    assert 'expect(page.locator(\'.cart\')).to_contain_text("Backpack")' in code
    assert "expect(item_name)" not in code and "expect(rows)" not in code
    ok = dict(item_name="Sauce Labs Backpack", price=" $29.99 ", rows=1)
    page = type("P", (), {"locator": lambda self, s: s})()
    _run(code, **ok)(page)  # (the right cart passes)
    for wrong in ({"item_name": "Bike Light"}, {"price": "$9.99"}, {"rows": 2},
                  {"item_name": "Sauce Labs Backpack + Bike Light"}):
        with pytest.raises(AssertionError):  # (every check is still evaluated: a wrong value fails)
            _run(code, **{**ok, **wrong})(page)


def test_nothing_changes_without_a_value_read():
    code = 'def test_x(page):\n    expect(page.locator("a")).to_have_text("x")\n'
    assert fix_value_expects(code) == (code, [])


def test_page_address_and_title_keep_playwrights_waiting_and_inline_reads_become_asserts():
    """Live hybrid run (26 Nov): `expect(page.url).to_contain("/inventory.html")` failed with the same ValueError."""
    code, fixes = fix_value_expects('from playwright.sync_api import expect\n\n\ndef test_x(page):\n'
                                    '    expect(page.url).to_contain("/inventory.html")\n'
                                    '    expect(page.title()).to_be("Swag Labs")\n'
                                    '    expect(page.locator(".n").inner_text()).to_contain("Backpack")\n')
    assert 'expect(page).to_have_url(re.compile(re.escape(str("/inventory.html"))))' in code
    assert 'expect(page).to_have_title("Swag Labs")' in code
    assert 'assert str("Backpack") in str(page.locator(".n").inner_text())' in code
    assert code.startswith("import re\n") and len(fixes) == 3
    ast.parse(code)
