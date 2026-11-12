"""What the user's own runs got wrong (Nov 2, 2026) - runs/opensource-demo.orangehrmlive.com_20261102_130741 and
runs/ginandjuice.shop_20261102_124907 - each one fixed and kept fixed here (the pages below are built like theirs):
  * OrangeHRM's 'Punch In' form has no method and no action (Vue sends it to its API): it looked like a GET form that
    only reads, so exploring learned 'In' and a test clicked it - a real punch-in on the shared demo (01:43 PM);
  * the users table's delete button is <button><i class="bi-trash"></i></button>: without words it was named by its
    CSS classes, clicked, and only the website's own 'Cannot be deleted' stopped it;
  * emptying a box already shows 'Required' under it; the click then showed a second 'Required' - the same words,
    so 'no error message was shown' (the trace's pictures show both);
  * the filter forms ('Username / User Role / Status' + 'Search') got 'submitting it empty is rejected';
  * ginandjuice's cart shows the quantity as a list: its text holds every choice ('Qty: 1 2 3'), so it read 1 for 2;
  * one slow answer of the start page (20 s) made the verdict 'Insufficient Evidence' while 28 pages were tested;
  * the AI's eyes (backend/vision.py): its verdict may clear a failure or ask a person, never more."""
import pytest

from backend.agents.failure_analysis import classify


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    p = browser.new_page(viewport={"width": 1366, "height": 900})
    yield p
    p.close()


PUNCH = ('<!doctype html><html><body><h6>Punch In</h6><form class="oxd-form"><label>Date*</label>'
         '<input placeholder="yyyy-dd-mm" value="2026-02-11"><label>Time*</label><input placeholder="hh:mm" value="01:43 PM">'
         '<textarea placeholder="Type here"></textarea><button type="submit" class="oxd-button oxd-button--medium">In'
         '</button></form><form class="oxd-form"><input placeholder="Type for hints..."><button type="submit" '
         'class="oxd-button">Search</button></form><form method="get" action="/find"><input name="q"><button '
         'type="submit">Go</button></form><table><tr><td>Admin</td><td><button class="oxd-icon-button '
         'oxd-table-cell-action-space"><i class="oxd-icon bi-trash"></i></button></td></tr></table></body></html>')


def _buttons(page):
    from backend.agents.discovery import EXTRACT_JS
    page.set_content(PUNCH)
    return {(b.get("text") or "").split("\n")[0]: b for b in page.evaluate(EXTRACT_JS)["buttons"]}


def test_a_form_the_page_script_sends_is_never_clicked_while_exploring(page):
    from backend.observe import sends_form
    btn = _buttons(page)
    assert btn["In"]["form_method"] == "script"  # (was: 'get' - "a GET form only reads")
    assert sends_form(btn["In"])
    assert not sends_form(btn["Search"])  # a filter form's button only reads: it is still learned
    assert btn["Go"]["form_method"] == "get" and not sends_form(btn["Go"])


def _conftest_text(name):
    """A string constant of templates/conftest.py (read, not imported: importing it would patch Playwright)."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path("backend/templates/conftest.py").read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == name)


def test_a_button_that_only_shows_a_trash_icon_is_protected(page, monkeypatch):
    from backend.actions import action_risk
    from tests.test_gin_shop_lessons import _guard
    trash = next(b for t, b in _buttons(page).items() if "trash" in t)
    assert action_risk(trash["text"], trash["selector"]) == "protected"  # (was: 'safe' - clicked while exploring)
    names = page.locator("button.oxd-icon-button").evaluate(_conftest_text("CONTROL_TEXT_JS"), False)
    assert _guard(monkeypatch)(names), names  # the generated tests' guard refuses it too


def test_a_second_required_under_the_next_box_is_the_websites_answer(page):
    from backend.agents.script_generator import LINES_JS, VALIDATION_JS
    page.set_content('<form><input placeholder="yyyy-dd-mm"><div id="d"></div><input placeholder="hh:mm">'
                     '<span class="oxd-input-field-error-message">Required</span><p>* Required</p></form>')
    before = page.evaluate(LINES_JS)  # (emptying the Time box already showed its 'Required')
    page.evaluate("document.getElementById('d').innerHTML = "
                  "'<span class=\"oxd-input-field-error-message\">Required</span>'")
    found = page.evaluate(VALIDATION_JS, before)
    assert found["message"] == "Required" and found["marked"] >= 1, found  # (was: nothing new - "no error message")


def test_a_cart_line_whose_quantity_is_a_list_reads_the_chosen_number(page):
    from backend.agents.script_generator import CART_HELPERS
    ns = {}
    exec("import re\n" + CART_HELPERS, ns)
    page.set_content('<ul><li class="cart-item"><h3>PINEAPPLE EDITION COCKTAIL</h3><p>$30.50</p><label>Qty:</label>'
                     '<select><option>1</option><option selected>2</option><option>3</option></select>'
                     '<button>remove</button></li></ul>')
    row = ns["_cart_row"](page, "PINEAPPLE EDITION")
    assert ns["_line_qty"](row) == 2  # (was: 1 - the list's text is '1 2 3')
    assert ns["_one_more"](row) and ns["_line_qty"](row) == 3


def _page_with(form):
    return {"url": "https://hr.test/web/index.php/admin/viewSystemUsers", "slug": "users", "title": "OrangeHRM",
            "auth": True, "status": 200, "page_type": "admin", "buttons": [], "inputs": [], "links": [],
            "itemNames": [], "behaviour": [], "forms": [form]}


def test_a_filter_form_with_a_search_button_gets_no_empty_form_test():
    from backend.agents.test_design import rule_based_cases
    boxes = [{"name": "", "id": "", "type": "text", "selector": f"form input >> nth={n}", "required": False,
              "label": label} for n, label in enumerate(("Username", "Employee Name", "Type for hints..."))]
    search = {"index": 0, "selector": "form >> nth=0", "action": "", "method": "", "fields": boxes,
              "submit": {"text": "Search", "selector": "button.oxd-button"}}
    assert "form0_required_validation" not in {c["id"] for c in rule_based_cases(_page_with(search))}
    save = dict(search, submit={"text": "Save", "selector": "button.oxd-button"})
    # A Save label alone does not establish that any field is required.
    assert "form0_required_validation" not in {c["id"] for c in rule_based_cases(_page_with(save))}
    save["fields"]=[{**boxes[0],"required":True},*boxes[1:]]
    assert "form0_required_validation" in {c["id"] for c in rule_based_cases(_page_with(save))}


def _failed(test, error, file="test_checks.py", vision=None, **kw):
    return dict({"nodeid": f"{file}::{test}", "file": file, "test": test, "outcome": "failed", "error": error,
                 "error_type": "AssertionError", **({"vision": vision} if vision else {})}, **kw)


def test_what_the_ai_saw_may_clear_a_failure_or_ask_a_person_never_more():
    empty = "E   AssertionError: Empty form: no error message was shown"
    mistake = {"verdict": "test_mistake", "seen": "Date* Required Time* Required", "reason": "The boxes say Required."}
    bug = {"verdict": "website_bug", "seen": "SORRY! NO RESULT FOUND", "reason": "The search finds nothing."}
    assert classify(_failed("test_check_35", empty))[0] == "product_defect"  # the rules alone
    cat, why, _ = classify(_failed("test_check_35", empty, vision=mistake))
    assert cat == "test_mistake" and "Required" in why
    learned = "E   AssertionError: 'Search' changed nothing"
    assert classify(_failed("test_learned_6", learned, "test_learned.py", vision=bug))[0] == "suspect"  # not a bug
    cat, _, confidence = classify(_failed("test_check_1", "E   assert 'limited' in 'sorry'", vision=bug))
    assert (cat, confidence) == ("product_defect", "high")  # a failed check the AI saw too: confirmed
    script = "E   NameError: name 'x' is not defined"
    r = _failed("test_x", script, vision=mistake, error_type="NameError")
    assert classify(r)[0] == "test_defect"  # a broken script stays one
    assert classify(_failed("test_y", empty, vision=mistake, flaky=True))[0] == "flaky"


def test_the_ai_is_shown_only_failures_a_picture_can_show(monkeypatch, tmp_path):
    from backend import vision
    shot = tmp_path / "f.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    asked = []

    def fake(prompt, shape, **kw):
        asked.append(kw.get("test"))
        return vision.FailureSeen(verdict="test_mistake", seen="Required", reason="The box says Required.")
    monkeypatch.setattr(vision, "vision_enabled", lambda: True)
    monkeypatch.setattr(vision, "ask_structured", fake)
    src = ("    def test_check_35(page, console_errors):\n>       assert refused\n"
           "E   AssertionError: Empty form: no error message was shown")
    state = {"run_dir": str(tmp_path), "test_cases": [], "app_map": [
        {"url": "https://hr.test/auth/login", "page_type": "login", "inputs": [{"type": "password"}]}],
        "results": [_failed("test_check_35", src, screenshot="f.png", url="https://hr.test/punchIn"),
                    _failed("test_no_console_errors[home]", "E   JavaScript errors on /: x", "test_site.py",
                            screenshot="f.png"),
                    _failed("test_login_ok", "E   AssertionError: still on the login page", screenshot="f.png",
                            url="https://hr.test/auth/login")]}
    assert vision.review_results(state) == 1
    assert asked == ["test_check_35"]  # (not the JavaScript error, not the login page; 'console_errors' in its code)
    assert state["results"][0]["vision"]["verdict"] == "test_mistake"
    assert (tmp_path / "vision_failures.json").exists()
    assert vision.review_results(state) == 0  # the same failure again: from the cache, not asked twice


def test_the_picture_before_the_last_step_comes_from_the_recording(browser, tmp_path):
    from backend.vision import before_picture
    ctx = browser.new_context()
    ctx.tracing.start(screenshots=True, snapshots=False)
    p = ctx.new_page()
    p.set_content("<input id='a'><button onclick=\"document.body.innerHTML='<h1>Sent</h1>'\">Send</button>")
    p.fill("#a", "hello")
    p.wait_for_timeout(300)
    p.click("button")
    p.wait_for_timeout(300)
    ctx.tracing.stop(path=str(tmp_path / "t.zip"))
    ctx.close()
    img = before_picture(tmp_path / "t.zip")
    assert img and img[:2] == b"\xff\xd8"  # a JPEG frame of the screen before the click


def test_an_own_said_helper_of_the_ai_is_replaced():
    from backend.agents.script_generator import _with_said
    code = ("import re\nimport pytest\n\ndef _said(page):\n    return [page.locator('text=Product added').inner_text()]\n"
            "\ndef test_ai_flow_1(page):\n    assert any('x' in m for m in _said(page))\n")
    out = _with_said(code)
    assert "text=Product added" not in out and out.count("def _said(") == 1  # (was: it found only what it guessed)


def test_a_slow_start_page_is_a_risk_when_the_website_was_tested():
    from backend.agents.reporter import decide_verdict
    ok = [{"url": f"https://hr.test/p{n}", "status": 200, "auth": True} for n in range(3)]
    state = {"app_map": [{"url": "https://hr.test", "error": "Page.goto: Timeout 20000ms exceeded."}] + ok,
             "results": [{"nodeid": "t::a", "file": "test_site.py", "test": "test_page_loads[a]", "outcome": "passed"}],
             "failures": [], "login": {"found": True, "logged_in": True, "evidence": ["the password box is gone"]},
             "crawl": {}, "test_cases": []}
    verdict, reasons, gates = decide_verdict(state)
    assert gates[0]["id"] == "start_page" and gates[0]["status"] == "risk", gates[0]
    assert verdict != "Insufficient Evidence" or "start page" not in " ".join(reasons)  # (was: the only reason)
    state["app_map"] = state["app_map"][:1]  # nothing else opened either: still not enough evidence
    assert decide_verdict(state)[0] == "Insufficient Evidence"
