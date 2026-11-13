"""Agent 3 — Automation (Script) Generation Agent.

Turns the test cases into real Playwright + PyTest scripts in runs/<run_id>/generated_tests/
(see script_generator_agent for the files) - one test function per test case, each with its own result.

With an LLM: the model writes the code of its own journeys; we validate it (syntax + safety) and ask it to fix its
own mistakes once. If it still fails, its journeys are left out (the built-in test cases still run).
"""
import ast
import json
import re
import shutil
from pathlib import Path
from pprint import pformat

from ..ai_grounding import grounding_problem
from ..config import settings
from ..excel import write_workbook
from ..form_targets import FORM_TARGET_HELPER
from ..llm import LLMError, ask_llm, extract_code, load_prompt
from ..navigation import OPEN_PATH_HELPER, opener_path
from ..observe import PICTURES_JS, REGION_JS
from ..state import QAState
from .discovery import ITEMS_JS, MAIN_TEXT_JS
from .test_design import _observed, features, lean, on_screen, safe_buttons

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

SYSTEM = (
    "You are an expert test automation engineer. You write clean, reliable Playwright (Python, SYNC API) "
    "+ PyTest tests. You only output Python code."
)


# Static checks for generated code (the runtime sandbox in templates/conftest.py is the second line of defence).
# ALLOW-list: only these modules may be imported (anything else - os, sys, socket, importlib, ... - is refused).
ALLOWED_IMPORTS = {"re", "json", "math", "random", "string", "datetime", "time", "collections", "itertools",
                   "functools", "typing", "decimal", "pytest"}
ALLOWED_FROM = ALLOWED_IMPORTS | {"playwright.sync_api", "urllib.parse"}
ALLOWED_PLAYWRIGHT = {"expect", "Page", "Locator", "Error", "TimeoutError", "FrameLocator", "ElementHandle",
                      "Response", "Request", "Dialog", "Keyboard", "Mouse"}
BANNED_CALLS = {"eval", "exec", "open", "__import__", "compile", "getattr", "setattr", "delattr", "globals", "locals",
                "vars", "breakpoint", "input", "exit", "quit", "help", "memoryview", "sync_playwright"}
# attributes that could switch the sandbox off or leave it: new unguarded browsers, removing the network guard,
# exposing Python to the page, writing files through the browser, importing modules through pytest
BANNED_ATTRS = {"route", "unroute", "unroute_all", "route_from_har", "route_web_socket", "expose_function",
                "expose_binding", "new_context", "browser", "launch", "launch_persistent_context", "connect",
                "connect_over_cdp", "new_cdp_session", "new_browser_cdp_session", "save_as", "pdf", "tracing", "video",
                "storage_state", "importorskip", "MonkeyPatch", "register_assert_rewrite", "getfixturevalue", "sleep"}
BANNED_FIXTURES = {"request", "browser", "_shared", "monkeypatch", "pytestconfig", "tmp_path_factory"}
MAX_WAIT_MS = 5000  # wait for a condition (expect / wait_for_*), not for a fixed time


def validate_script(code: str, need_tests: bool = True) -> str | None:
    """Static checks before we run AI-written code. Returns an error message, or None if OK.
    need_tests=False: a helper module (the steps of the large test cases) - no test_ functions needed."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    tests = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name not in ALLOWED_IMPORTS and not re.fullmatch(r"steps_\w+", a.name):
                    return f"Banned import: {a.name} (allowed: {', '.join(sorted(ALLOWED_IMPORTS))})"
        if isinstance(node, ast.ImportFrom):
            if node.level or (node.module not in ALLOWED_FROM and not re.fullmatch(r"steps_\w+", node.module or "")):
                return f"Banned import: from {node.module}"
            if node.module == "playwright.sync_api":
                bad = [a.name for a in node.names if a.name not in ALLOWED_PLAYWRIGHT]
                if bad:
                    return f"Banned import: {', '.join(bad)} from playwright.sync_api"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
            return f"Banned call: {node.func.id}()"
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                return f"Banned attribute: .{node.attr} (no hidden / internal attributes)"
            if node.attr in BANNED_ATTRS:
                return f"Banned attribute: .{node.attr}"
            if node.attr in ("post", "put", "patch", "delete", "fetch") and (
                    (isinstance(node.value, ast.Attribute) and node.value.attr == "request")
                    or (isinstance(node.value, ast.Name) and node.value.id == "request")):
                return f"Banned call: request.{node.attr}() (tests may only read, never send data)"
        if isinstance(node, ast.Name) and node.id in ("pytest_plugins", "__builtins__", "__loader__", "__spec__"):
            return f"Banned name: {node.id}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "wait_for_timeout" and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, (int, float)) and node.args[0].value > MAX_WAIT_MS:
                return f"wait_for_timeout({node.args[0].value}) is too long: wait for a condition with expect() instead"
            if node.func.attr == "set_input_files" and node.args and not isinstance(node.args[0], ast.Dict):
                return "set_input_files may only use an in-memory file ({'name', 'mimeType', 'buffer'}), not a path"
        if isinstance(node, ast.FunctionDef):
            if node.name.startswith("pytest_"):
                return f"Do not define pytest hooks ({node.name})"
            if node.name in {"page", "browser", "console_errors", "qa_login", "run_steps", "_shared"}:
                return f"Do not redefine fixture `{node.name}`"
            args = {a.arg for a in node.args.args}
            if node.name.startswith(("test_", "step_")) and args & BANNED_FIXTURES:
                return f"{node.name} may not use the fixture(s) {', '.join(sorted(args & BANNED_FIXTURES))}"
            if node.name.startswith("test_"):
                tests += 1
                if "page" not in args:
                    return f"{node.name} must take the `page` fixture"
    if tests == 0 and need_tests:
        return "No test_ functions found"
    return None


# ---------------------------------------------------------------- template generator (no LLM)

def _ident(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", s).strip("_").lower()
    return s if s and not s[0].isdigit() else f"t_{s}"


def _submit_locator(form: dict) -> str:
    """Code that finds the form's submit button (its own selector, or the first submit inside the form)."""
    if form["submit"].get("selector"):
        return f"page.locator({form['submit']['selector']!r}).first"
    return (f"page.locator({form['selector']!r}).first"
            ".locator('[type=submit], button:not([type])').first")


# ---- one test per control (cases made by test_design.control_cases)

def _dropdown_test(cid: str, title: str, c: dict) -> list[str]:
    return [
        f"def test_{cid}(page, console_errors):",
        f'    """{title}"""',
        "    page.goto(URL)",
        "    _settle(page)",
        f"    sel = {c['selector']!r}",
        "    errors_before = len(console_errors)",
        "    expect(page.locator(sel).first, 'the dropdown should be visible').to_be_visible()",
        f"    for value in {c['options']!r}:",
        "        page.locator(sel).first.select_option(value)",
        "        _settle(page)  # some dropdowns reload the page",
        "        expect(page.locator(sel).first, f'option {value!r} should be selected').to_have_value(value)",
        "    new_errors = console_errors[errors_before:]",
        "    assert not new_errors, 'Choosing options caused JavaScript errors:\\n' + '\\n'.join(new_errors[:5])",
        "",
    ]


def _radio_test(cid: str, title: str, c: dict) -> list[str]:
    return [
        f"def test_{cid}(page):",
        f'    """{title}"""',
        "    page.goto(URL)",
        "    _settle(page)",
        f"    seen = {c['radios']!r}  # (the choices exploring saw)",
        "    radios = [r for r in seen if page.locator(r).count()]  # (a choice may be shown only in another state)",
        "    for sel in radios:",
        "        _pick(page.locator(sel).first)",
        "        expect(page.locator(sel).first, f'{sel} should be selected').to_be_checked()",
        "        # all the choices read at the same moment (not one after the other, while the page may still change)",
        "        on = [r for r in radios if page.locator(r).first.is_checked()]",
        "        assert on == [sel], f'After picking {sel}, the selected choice(s) are {on} - only {sel} should be'",
        "    missing = [r for r in seen if r not in radios]",
        "    if missing:  # (not known whether they work: not on the page now - e.g. only while the cart holds an item)",
        "        _inconclusive(f'the choice(s) {missing} seen while exploring are not on the page now - not tested; '",
        "                      f'the other choices work')",
        "",
    ]


def _checkbox_test(cid: str, title: str, c: dict) -> list[str]:
    return [
        f"def test_{cid}(page):",
        f'    """{title}"""',
        "    page.goto(URL)",
        "    _settle(page)",
        f"    box = page.locator({c['selector']!r})",
        "    _pick(box)",
        "    expect(box, 'it should be ticked').to_be_checked()",
        "    set_user_checked(box, False)",
        "    expect(box, 'it should be unticked').not_to_be_checked()",
        "",
    ]


def _opens_test(cid: str, title: str, c: dict) -> list[str]:
    action = [
        "    opened = False",
        "    for letters in ('a', 'in', 'ind', 'an'):  # suggestion lists usually start after 1-3 letters",
        "        el.fill('')",
        "        el.press_sequentially(letters, delay=100)",
        "        page.wait_for_timeout(1200)",
        "        # a list that appears on the page, or the browser's own suggestion list (<datalist>) with matches",
        "        if _shown(page) > before or el.evaluate(\"e => !!(e.list && [...e.list.options].some(\"",
        "                                                \"o => o.value.toLowerCase().includes(e.value.toLowerCase())))\"):",
        "            opened = True",
        "            break",
        "    assert opened, 'No suggestions appeared while typing'",
    ] if c.get("typing") else [
        "    text_before = len(page.locator('body').inner_text())",
        "    el.click(timeout=5000)",
        "    page.wait_for_timeout(1000)",
        "    # (more visible elements, or more visible text: a <details> part that opens shows its text)",
        "    assert _shown(page) > before or len(page.locator('body').inner_text()) > text_before, (",
        "        'Clicking it did not open anything (no list, calendar or panel appeared)')",
    ]
    return [
        f"def test_{cid}(page, console_errors):",
        f'    """{title}"""',
        "    page.goto(URL)",
        "    _settle(page)",
        f"    el = page.locator({c['selector']!r}).first",
        "    expect(el, 'it should be visible').to_be_visible()",
        "    before = _shown(page)",
        "    errors_before = len(console_errors)",
        *action,
        "    new_errors = console_errors[errors_before:]",
        "    assert not new_errors, 'Using it caused JavaScript errors:\\n' + '\\n'.join(new_errors[:5])",
        "",
    ]


def _head(cid: str, title: str, *fixtures: str) -> list[str]:
    return [f"def test_{cid}({', '.join(('page',) + fixtures)}):", f'    """{title}"""', "    page.goto(URL)", "    _settle(page)"]


def _no_new_errors(what: str) -> list[str]:
    return ["    new_errors = console_errors[errors_before:]",
            f"    assert not new_errors, '{what} caused JavaScript errors:\\n' + '\\n'.join(new_errors[:5])", ""]


def _tabs_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title, "console_errors") + [
        f"    tabs = {c['tabs']!r}",
        f"    seen = {c.get('seen') or {}!r}  # what each tab showed while exploring",
        "    errors_before = len(console_errors)",
        "    for sel in tabs:",
        "        tab = page.locator(sel).first",
        "        before = page.locator('body').inner_text()",
        "        tab.click(timeout=5000)",
        "        page.wait_for_timeout(600)",
        "        if seen.get(sel):  # its OWN content must show - not only 'something changed'",
        "            now = page.locator('body').inner_text()",
        "            assert any(s.replace('[frame] ', '') in now for s in seen[sel]), (",
        "                f'The tab {sel} did not show its content (while exploring it showed {seen[sel][0]!r})')",
        "            continue",
        "        active = tab.evaluate(\"el => el.getAttribute('aria-selected') === 'true' || \"",
        "                              \"/active|selected|current/.test(el.className + ' ' + (el.parentElement ? el.parentElement.className : ''))\")",
        "        assert active or page.locator('body').inner_text() != before, f'Clicking the tab {sel} showed nothing new'",
    ] + _no_new_errors("Switching tabs")


POPUP = "[role=dialog], [aria-modal=true], dialog[open], .modal.show, .modal.in, .modal[style*='display: block']"
CLOSE = ("[data-dismiss=modal], [data-bs-dismiss=modal], [aria-label=Close], [aria-label=close], .close, .btn-close, "
         "button:has-text('Close')")


def _modal_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title, "console_errors") + [
        "    errors_before = len(console_errors)",
        "    before = _shown(page)",
        f"    page.locator({c['selector']!r}).first.click(timeout=5000)",
        "    page.wait_for_timeout(1000)",
        f"    popup = page.locator({POPUP!r}).first",
        "    assert popup.count() or _shown(page) > before, 'Clicking it did not open a popup'",
        "    if popup.count():",
        "        page.keyboard.press('Escape')",
        "        page.wait_for_timeout(600)",
        "        if popup.is_visible():",
        f"            close = popup.locator({CLOSE!r}).first",
        "            if close.count():",
        "                close.click(timeout=5000)",
        "                page.wait_for_timeout(600)",
        "        assert not popup.is_visible(), 'The popup could not be closed (Esc or its Close button)'",
    ] + _no_new_errors("Opening the popup")


def _dialog_test(cid: str, title: str, c: dict) -> list[str]:
    said = c.get("said") or ""  # 'alert: Settings saved' - what the box said while exploring
    kind, _, message = said.partition(": ")
    return _head(cid, title) + [
        "    seen = []",
        "",
        "    def on_dialog(d):",
        "        seen.append((d.type, d.message))",
        "        d.accept('QA Tester') if d.type == 'prompt' else d.accept()",
        "",
        "    page.on('dialog', on_dialog)",
        f"    page.locator({c['selector']!r}).first.click(timeout=5000)",
        "    page.wait_for_timeout(1500)",
        "    assert seen, 'No alert / confirm box appeared'",
        *([f"    assert seen[0][0] == {kind!r}, f'A {{seen[0][0]}} box appeared - while exploring it was a {kind}'",
           f"    said = {message!r}",
           "    assert _same_words(seen[0][1], said), f'The box said {seen[0][1]!r} - while exploring it said {said!r}'"]
          if kind and message else []),
        "    if seen[0][0] == 'prompt':  # (answered 'QA Tester': where the page shows the answer, it is written down)",
        "        if 'QA Tester' in page.locator('body').inner_text():",
        "            print('[qa-step] the page shows the answer QA Tester')",
        "",
    ]


def _sort_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title) + [
        f"    head = page.locator({c['selector']!r}).first",
        "    before = head.evaluate(COLUMN_JS)",
        "    if len(set(before)) < 2:",
        "        _inconclusive('the column has fewer than 2 different values: there is nothing to sort')",
        "        return",
        "    head.click(timeout=5000)",
        "    page.wait_for_timeout(800)",
        "    first = head.evaluate(COLUMN_JS)",
        "    o1 = _order(first)",
        "    assert o1, f'After clicking the header the column is not in order: {first[:8]}'",
        "    head.click(timeout=5000)",
        "    page.wait_for_timeout(800)",
        "    second = head.evaluate(COLUMN_JS)",
        "    o2 = _order(second)",
        "    assert o2 and o2 != o1, (f'A second click should reverse the order ({o1}); the column is '",
        "                             f\"{o2 or 'not in order'}: {second[:8]}\")",
        "",
    ]


def _table_search_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title) + [
        f"    T = {{'table': {c['table']!r}, 'box': {c['selector']!r}}}",
        "    box = page.locator(T['box']).first",
        "    expect(box, 'the table\\'s search box should be visible').to_be_visible()",
        "    every = _table_rows(page, T['table'])",
        "    word = _table_word(every)",
        "    if not word:",
        "        _inconclusive('no word in the table that only some rows have')",
        "        return",
        "    box.fill(word)",
        "    page.wait_for_timeout(900)",
        "    shown = _table_rows(page, T['table'])",
        "    assert shown, f\"Searching '{word}' (taken from the table) shows no rows\"",
        "    other = [r for r in shown if word.lower() not in r.lower()]",
        "    assert not other, f\"Searching '{word}' also shows rows without it: {other[:3]}\"",
        "    box.fill(word.upper())",
        "    page.wait_for_timeout(900)",
        "    upper = _table_rows(page, T['table'])",
        "    assert upper == shown, (f\"Searching '{word.upper()}' shows {len(upper)} row(s), '{word}' showed \"",
        "                            f\"{len(shown)}: the search depends on upper / lower case\")",
        "    box.fill('zqxwv nothing like this')",
        "    page.wait_for_timeout(900)",
        "    assert not _table_rows(page, T['table']), 'A word that is nowhere still shows rows'",
        "    box.fill('')",
        "    page.wait_for_timeout(900)",
        "    assert len(_table_rows(page, T['table'])) == len(every), 'Clearing the search does not show every row again'",
        "",
    ]


def _page_size_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title) + [
        f"    size_box = page.locator({c['selector']!r}).first",
        f"    for n in {c['sizes']!r}:",
        "        size_box.select_option(n)",
        "        page.wait_for_timeout(800)",
        f"        rows = _table_rows(page, {c['table']!r})",
        "        assert rows, f'With {n} rows per page the table is empty'",
        "        assert len(rows) <= int(n), f'With {n} rows per page the table shows {len(rows)} rows'",
        "",
    ]


def _download_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title) + [
        f"    link = page.locator({c['selector']!r}).first",
        "    expect(link, 'the download link should be visible').to_be_visible()",
        "    with page.expect_download(timeout=20000) as info:",
        "        link.click()",
        "    d = info.value",
        "    assert d.failure() is None, f'The download failed: {d.failure()}'",
        *([f"    assert d.suggested_filename.lower().endswith('.{c['ext'].lower()}'), (",
           f"        f'The file is {{d.suggested_filename}} - expected a .{c['ext']} file')"] if c.get("ext") else []),
        "    print(f'[qa-step] downloaded {d.suggested_filename}')",
        "",
    ]


def _changes_test(cid: str, title: str, c: dict, action: list[str], what: str) -> list[str]:
    seen = [s.replace("[frame] ", "") for s in c.get("seen") or []]
    return _head(cid, title, "console_errors") + [
        "    errors_before = len(console_errors)",
        f"    el = page.locator({c['selector']!r}).first",
        "    expect(el, 'it should be visible').to_be_visible()",
        "    before, shown = page.locator('body').inner_text(), _shown(page)",
        *action,
        "    page.wait_for_timeout(1000)",
        f"    assert page.locator('body').inner_text() != before or _shown(page) != shown, {what!r}",
        *([f"    seen = {seen!r}  # what it showed while exploring: THAT must show again",
           "    now = page.locator('body').inner_text()",
           "    assert any(s in now for s in seen), f'It changed the page, but not to what it showed while exploring: {seen[0]!r}'"]
          if seen else []),
    ] + _no_new_errors("It")


def _next_test(cid, title, c):
    return _changes_test(cid, title, c, ["    el.click(timeout=5000)", "    _settle(page)"],
                         "Clicking it did not show other items")


def _hover_test(cid, title, c):
    return _changes_test(cid, title, c, [
        "    def opened():  # (a menu can fade in: watched for a moment)",
        "        for _ in range(8):",
        "            if page.locator('body').inner_text() != before or _shown(page) != shown:",
        "                return True",
        "            page.wait_for_timeout(250)",
        "        return False",
        "    el.hover(timeout=5000)",
        "    toggle = el.locator('[aria-haspopup], [aria-expanded], [data-bs-toggle], [data-toggle], .dropdown-toggle').first",
        "    if not opened() and toggle.count():",
        "        toggle.click(timeout=5000)  # a menu that opens on a click, not on pointing",
        "    if not opened():  # some menus react only to a real move of the mouse onto them",
        "        page.mouse.move(1, 1)",
        "        el.hover(timeout=5000)",
        "        opened()",
    ], "Pointing at it (or clicking its menu button) showed nothing (no menu / details)")


def _drag_test(cid, title, c):
    return _changes_test(cid, title, c, [f"    el.drag_to(page.locator({c['target']!r}).first, timeout=10000)"],
                         "Dragging it changed nothing on the page")


def _slider_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title) + [
        f"    s = page.locator({c['selector']!r}).first",
        "    lo, hi = s.evaluate(\"el => [el.min || '0', el.max || '100']\")",
        "    for v in (lo, hi):",
        "        try:",
        "            s.fill(v)",
        "        except Exception:  # (a range box can't always be filled: set it like a hand moving it - input + change)",
        "            s.evaluate(SET_RANGE_JS, v)",
        "        expect(s, f'the slider should go to {v}').to_have_value(v)",
        "",
    ]


def _upload_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title) + [
        f"    box = page.locator({c['selector']!r}).first",
        "    box.set_input_files({'name': 'agentic-qa-test.txt', 'mimeType': 'text/plain', 'buffer': b'Agentic QA test file'})",
        "    names = box.evaluate('el => [...el.files].map(f => f.name)')",
        "    assert names == ['agentic-qa-test.txt'], f'The file was not accepted (box has: {names})'",
        "    # (the file is never sent: nothing is submitted)",
        "",
    ]


# Signing in like a person - also a two-step login (user name -> Continue -> password). Used by the login tests.
LOGIN_HELPER = r'''
def _shows(page, selector):
    try:
        return bool(selector) and page.locator(selector).first.is_visible()
    except Exception:
        return False


def _sign_in(page, form, user, password):
    """Fill the login form and send it. False = the password box never appeared (the user name was refused)."""
    if form.get('openers'):
        open_path(page, form['openers'], form.get('form') or form['user'])
    scope = page.locator(form['form']) if form.get('form') else page
    if form.get('form'):
        expect(scope, 'The login container must be unique').to_have_count(1)
    user_box = scope.locator(form["user"])
    expect(user_box, 'The observed login user field must be unique').to_have_count(1)
    expect(user_box, 'The login opener must reveal the user field').to_be_visible()
    user_box.fill(user)
    pw = scope.locator(form["password"])
    if form.get("two_step") or not _shows(page, form["password"]):
        if form.get("submit"):
            submit = page.locator(form["submit"])
            expect(submit, 'The recorded login submit must be unique').to_have_count(1)
            submit.click(timeout=5000)
        else:
            user_box.press("Enter")
        try:
            pw.wait_for(state="visible", timeout=8000)
        except Exception:
            return False
        pw.fill(password)
        button = scope.get_by_role("button", name=re.compile(r"\b(log ?in|sign ?in|submit|continue)\b", re.I))
        if button.count() > 1:
            raise AssertionError('Automation target ambiguous: login continuation button')
        if button.count() and button.is_visible():
            button.click(timeout=5000)
        else:
            pw.press("Enter")
    else:
        pw.fill(password)
        if form.get("submit"):
            submit = page.locator(form["submit"])
            expect(submit, 'The recorded login submit must be unique').to_have_count(1)
            submit.click(timeout=5000)
        else:
            pw.press("Enter")
    page.wait_for_timeout(1500)
    _settle(page)
    return True
'''
REFUSED = r"invalid|incorrect|wrong|failed|not match|error|cannot find|can.t find|not found|does not exist|no account"

# Clicking one button like a person. JavaScript errors count only when the page stayed the same: errors of the NEXT
# page belong to that page (it has its own "no JavaScript errors" check). A button that can't be brought on screen
# (a slide of a carousel that is not shown) can't be clicked by a person either -> 'unreachable', not a failure.
CLICK_HELPER = r'''
def _click_button(page, console_errors, btn):
    page.goto(URL)
    _settle(page)
    bad = []

    def on_response(r):
        if r.status >= 500 or (r.request.is_navigation_request() and r.status >= 400):
            bad.append(f"HTTP {r.status}  {r.url}")
    page.on("response", on_response)
    try:
        if btn["selector"]:
            el = page.locator(btn["selector"]).first
        else:
            el = page.locator("button, input[type=button], [role=button]").filter(
                has_text=re.compile(btn["pattern"], re.I)).first
        expect(el, f"button '{btn['text']}' should be visible").to_be_visible()
        errors_before, start = len(console_errors), page.url.split("#")[0]
        try:
            el.scroll_into_view_if_needed(timeout=3000)
            el.click(timeout=5000)
        except Exception as e:
            if "outside of the viewport" in str(e) or "not visible" in str(e):
                return "unreachable"
            raise
        page.wait_for_timeout(1000)
        new_errors = console_errors[errors_before:] if page.url.split("#")[0] == start else []
        assert not new_errors, f"Clicking '{btn['text']}' caused errors:\n" + "\n".join(new_errors[:5])
        assert not bad, f"Clicking '{btn['text']}' led to an error page:\n" + "\n".join(bad[:5])
        return "clicked"
    finally:
        page.remove_listener("response", on_response)
'''


def _login_lines(c: dict, user: str, password: str) -> list[str]:
    form = {k: c.get(k) for k in ("user", "password", "submit", "two_step")}
    return [
        f"    form = {form!r}",
        f"    reached = _sign_in(page, form, {user}, {password})",
        "    still_login = not reached or _shows(page, form['user']) or _shows(page, form['password'])",
    ]


def _login_wrong_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title) + _login_lines(c, "'agentic-qa-test'", "'wrong-password-123'") + [
        f"    error = page.get_by_text(re.compile(r'{REFUSED}', re.I)).count()",
        "    assert still_login or error, f'A wrong password was accepted (now on {page.url})'",
        "",
    ]


def _login_ok_test(cid: str, title: str, c: dict) -> list[str]:
    return _head(cid, title, "qa_login") + _login_lines(c, "qa_login[0]", "qa_login[1]") + [
        "    assert not still_login, 'Login with the test account (TEST_USERNAME / TEST_PASSWORD in .env) did not work'",
        "",
    ]


CONTROL_TESTS = {"dropdown": _dropdown_test, "radio": _radio_test, "checkbox": _checkbox_test, "opens": _opens_test,
                 "tabs": _tabs_test, "modal": _modal_test, "dialog": _dialog_test, "sort": _sort_test,
                 "next": _next_test, "hover": _hover_test, "drag": _drag_test, "slider": _slider_test,
                 "upload": _upload_test, "login_wrong": _login_wrong_test, "login_ok": _login_ok_test,
                 "table_search": _table_search_test, "page_size": _page_size_test, "download": _download_test}

# the helpers of the stronger checks (Step 6), in every steps module
TABLE_HELPERS = r'''
# the cells of a column (the clicked header's position in its row) and whether they are in order
COLUMN_JS = """el => { const th = el.closest('th, td') || el, row = th.parentElement, table = th.closest('table');
  if (!row || !table) return [];
  const idx = [...row.children].indexOf(th);
  return [...table.querySelectorAll('tbody tr')].filter(r => r.offsetParent !== null)
    .map(r => r.children[idx] ? r.children[idx].innerText.trim() : '').filter(Boolean); }"""
SET_RANGE_JS = """(el, v) => { el.value = v; el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true})); }"""
EMPTY_ROW = re.compile(r'^\s*(no .{0,40}(found|match|results?)|nothing (found|to show)|no data|empty)\b', re.I)


def _sort_key(v):
    """Numbers as numbers (with a currency or %), dates as dates (2024-03-01, 01/03/2024), text without case."""
    t = v.strip()
    m = re.fullmatch(r'[^\d\-+]*([-+]?[\d,]*\.?\d+)\s*%?[^\d]*', t)
    if m and re.search(r'\d', t) and not re.search(r'[a-z]{2}', t, re.I):
        return (0, float(m.group(1).replace(',', '')))
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2}).*', t)
    if m:
        return (1, tuple(int(x) for x in m.groups()))
    m = re.fullmatch(r'(\d{1,2})[/.](\d{1,2})[/.](\d{4})', t)
    if m:
        return (1, (int(m.group(3)), int(m.group(2)), int(m.group(1))))
    return (2, t.casefold())


def _order(values):
    """'ascending' / 'descending' / None (not in order). Mixed kinds are compared as text."""
    keys = [_sort_key(v) for v in values]
    if len({k[0] for k in keys}) > 1:
        keys = [(2, v.strip().casefold()) for v in values]
    if keys == sorted(keys):
        return 'ascending'
    if keys == sorted(keys, reverse=True):
        return 'descending'
    return None


def _table_rows(page, table):
    """The texts of the table's visible rows - a 'No users found' row counts as none."""
    rows = page.locator(f'{table} tbody tr').all()
    out = []
    for r in rows:
        try:
            if r.is_visible():
                out.append(r.inner_text().strip())
        except Exception:
            pass
    return [r for r in out if r and not EMPTY_ROW.search(r)]


def _table_word(rows):
    """A word from the table that some rows have and others don't (a name, a role ...)."""
    import collections
    counts = collections.Counter(w for r in rows for w in set(re.findall(r'[A-Za-z]{4,}', r)))
    for w, n in counts.most_common():
        if 0 < n < len(rows):
            return w
    return ''


def _same_words(said, learned):
    want = set(re.findall(r'[a-z]{3,}', (learned or '').lower()))
    return not want or len(want & set(re.findall(r'[a-z]{3,}', (said or '').lower()))) >= len(want) / 2
'''


def template_script(page: dict, cases: list[dict], as_steps: bool = False) -> str:
    url = page["url"]
    links = sorted({l["href"].split("#")[0] for l in page.get("links", [])
                    if l["href"].startswith("http") and not l.get("external")})[:30]
    # Button text can contain icon names on separate lines (e.g. "book\nBook Cart"), so buttons
    # without a selector are found by a text pattern that allows any spacing between the words.
    buttons = []
    for n, b in enumerate(safe_buttons(page)):
        words = (b.get("text") or "").split()
        buttons.append({"id": f"b{n + 1}_{_ident(' '.join(words) or 'button')[:25]}",
                        "text": " ".join(words), "selector": b.get("selector"),
                        "pattern": r"\s*".join(re.escape(w) for w in words)})
    forms = {f"form{f['index']}": f for f in page.get("forms", [])}
    inputs = {_ident(f"maxlength_{i.get('name') or i.get('id') or 'field'}"): i for i in page.get("inputs", [])}
    feat = features(page)

    out = [
        f'"""Auto-generated tests for {url}"""',
        "import re",
        "import pytest",
        "from playwright.sync_api import expect",
        "",
        f"URL = {url!r}",
        f"GUEST = {not page.get('auth')}  # tested as a visitor (not logged in)",
        f"LINKS = {pformat(links, width=110)}",
        f"BUTTONS = {pformat(buttons, width=110)}",
        f"FEATURES = {pformat(feat, width=110)}",
        OPEN_PATH_HELPER,
        FORM_TARGET_HELPER,
        "",
        "",
        "def _settle(page):",
        "    try:",
        "        page.wait_for_load_state('networkidle', timeout=5000)",
        "    except Exception:",
        "        pass  # some sites never go fully idle",
        "",
        "",
        "def _number(box):",
        "    try:",
        "        return float(box.input_value() or 0)",
        "    except ValueError:",
        "        return 0.0",
        "",
        "",
        "def _shown(page):",
        "    \"\"\"How many things are visible on the page (goes up when a list, calendar or panel opens).\"\"\"",
        "    return page.evaluate(\"() => [...document.querySelectorAll('body *').values()].filter(e => {\"",
        "                         \"const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && \"",
        "                         \"getComputedStyle(e).visibility !== 'hidden'; }).length\")",
        "",
        "",
        "def _pick(box):",
        "    set_user_checked(box, True)",
        "",
        "",
        "def _search(page, words):",
        "    box = page.locator(FEATURES['search']).first",
        "    expect(box, 'the search box should be visible').to_be_visible()",
        "    box.fill(words)",
        "    _submit_search(page, box)",
        "    page.wait_for_timeout(1500)  # let the page show the results",
        "    _settle(page)",
        "",
        "",
        f"LINES_JS = {LINES_JS!r}",
        f"VALIDATION_JS = {VALIDATION_JS!r}",
        "APPROVE_JS = \"e => e.setAttribute('data-qa-approved', '1')\"  # (the sandbox lets this one planned click through)",
        LOGIN_HELPER,
        CLICK_HELPER,
        RESULT_HELPERS,
        TABLE_HELPERS,
        "",
        "def _validation_shown(page, form, before):",
        "    \"\"\"Did the website refuse the form? Browser validation (:invalid), aria-invalid, an error-styled element",
        "    or a NEW message like 'This field is required' (any wording / styling). Waits up to ~10 s: a form sent to",
        "    a slow server answers with a new page ('Your username is invalid!' came after 4 s).\"\"\"",
        "    for _ in range(20):",
        "        try:",
        "            page.wait_for_load_state('load', timeout=10000)",
        "            invalid = form.locator(':invalid').count() if form.count() else 0",
        "            found = page.evaluate(VALIDATION_JS, before)",
        "        except Exception:  # (the page was being replaced by the server's answer)",
        "            page.wait_for_timeout(500)",
        "            continue",
        "        if invalid or found['message'] or found['marked']:",
        "            return True, f\"invalid boxes: {invalid}, message: {found['message']!r}, marked: {found['marked']}\"",
        "        page.wait_for_timeout(500)",
        "    return False, ''",
        "",
    ]
    for c in cases:
        cid = _ident(c["id"])
        title = c["title"].replace('"', "'")
        if c.get("kind") in CONTROL_TESTS:
            out += CONTROL_TESTS[c["kind"]](cid, title, c)
        elif cid == "page_loads":
            out += [
                "def test_page_loads(page):",
                f'    """{title}"""',
                "    resp = page.goto(URL)",
                '    assert resp is not None and resp.status < 400, f"Page returned HTTP {resp.status if resp else None}"',
                '    assert page.title().strip() != "", "Page has no <title>"',
                "",
            ]
        elif cid == "no_console_errors":
            out += [
                "def test_no_console_errors(page, console_errors):",
                f'    """{title}"""',
                "    page.goto(URL)",
                "    _settle(page)",
                '    assert not console_errors, "Console errors:\\n" + "\\n".join(console_errors[:10])',
                "",
            ]
        elif cid == "buttons_click" and buttons:
            if as_steps:  # one step that clicks every button in turn
                out += ["def test_button_click(page, console_errors):", f'    """{title}"""',
                        "    for btn in BUTTONS:",
                        "        _click_button(page, console_errors, btn)", ""]
            else:
                out += ["@pytest.mark.parametrize('btn', BUTTONS, ids=[b['id'] for b in BUTTONS])",
                        "def test_button_click(page, console_errors, btn):", f'    """{title}"""',
                        "    if _click_button(page, console_errors, btn) == 'unreachable':",
                        "        pytest.skip(f\"'{btn['text']}' can't be reached on screen (e.g. a slide that is not shown)\")",
                        ""]
        elif cid == "search_finds_item" and feat["search"] and feat["word"]:
            out += [  # the RESULT LIST is read (the item cards), never the page's header / menus
                "def test_search_finds_item(page, console_errors):",
                f'    """{title}"""',
                "    page.goto(URL)",
                "    _settle(page)",
                "    errors_before = len(console_errors)",
                "    word = FEATURES['word']",
                "    _search(page, word)",
                "    new_errors = console_errors[errors_before:]",
                "    assert not new_errors, 'Searching caused JavaScript errors:\\n' + '\\n'.join(new_errors[:5])",
                "    if _item_landing(page, word, FEATURES.get('item_pages')):",
                "        return  # the shop opened the page of its only match - named with the word: found (no list to read)",
                "    found = _listed(page, hints=FEATURES.get('site_cards'))",
                "    names, hrefs = found.get('names') or [], found.get('hrefs') or []",
                "    if not names:  # no list of results to read (another layout): the page's own text must show the word",
                "        assert word.lower() in page.evaluate(MAIN_TEXT_JS).lower(), (",
                "            f\"Searching '{word}' shows no results (no list of items, no '{word}' on the page)\")",
                "        _inconclusive(f\"'{word}' is on the page after searching, but no list of results could be read\")",
                "        return",
                "    hits = [n for n in names if word.lower() in n.lower()]",
                "    if not hits and all(re.match(r'(view|read|see|open|more|details|learn|go to|continue)\\b', n, re.I)",
                "                        for n in names):  # cards that say 'VIEW POST', not the item's name: its own page",
                "        hits = [n for n, h in list(zip(names, hrefs))[:3] if h and _mentions(page, h, word, FEATURES.get('item_pages'))]",
                "    assert hits, f\"Searching '{word}' did not list it: the results are {names[:6]}\"",
                "    # a result without the word in its name may match its description or tags: its own page must say it",
                "    other = [(n, h) for n, h in zip(names, hrefs) if word.lower() not in n.lower()]",
                "    unrelated = [n for n, h in other[:3] if not _mentions(page, h, word, FEATURES.get('item_pages'))]",
                "    assert not unrelated, (f\"Searching '{word}' also shows items that don't match: {unrelated} \"",
                "                           f\"(their own pages do not mention '{word}')\")",
                "",
            ]
        elif cid == "search_no_results" and feat["search"]:
            out += [
                "def test_search_no_results(page, console_errors):",
                f'    """{title}"""',
                "    page.goto(URL)",
                "    _settle(page)",
                "    errors_before = len(console_errors)",
                "    _search(page, 'zzqx-no-such-item')",
                "    names = _listed(page, hints=FEATURES.get('site_cards')).get('names') or []",
                "    assert not names or _said_none(page), (f'A search for something that does not exist still shows '",
                "                                          f'{len(names)} item(s): {names[:5]}')",
                "    new_errors = console_errors[errors_before:]",
                "    assert not new_errors, 'Searching caused JavaScript errors:\\n' + '\\n'.join(new_errors[:5])",
                "",
            ]
        elif cid == "add_to_cart" and feat["add"]:
            out += [
                "def test_add_to_cart(page, console_errors):",
                f'    """{title}"""',
                "    page.goto(URL)",
                "    _settle(page)",
                "    btn = page.locator(FEATURES['add']).first",
                "    expect(btn, f\"the '{FEATURES['add_text']}' button should be visible\").to_be_visible()",
                "    before, said = page.locator('body').inner_text(), _messages(page)",
                "    errors_before = len(console_errors)",
                "    btn.click(timeout=5000)",
                "    page.wait_for_timeout(1500)",
                "    msgs = _judge(page, said, f\"Clicking '{FEATURES['add_text']}'\", GUEST)  # an error message fails it",
                "    after = page.locator('body').inner_text()",
                "    assert msgs or after != before, f\"Nothing changed after clicking '{FEATURES['add_text']}' (the cart was not updated)\"",
                "    new_errors = console_errors[errors_before:]",
                "    assert not new_errors, 'Adding to the cart caused JavaScript errors:\\n' + '\\n'.join(new_errors[:5])",
                "",
            ]
        elif cid == "quantity_plus_minus" and feat["qty"]:
            out += [
                "def test_quantity_plus_minus(page):",
                f'    """{title}"""',
                "    page.goto(URL)",
                "    _settle(page)",
                "    box = page.locator(FEATURES['qty']).first",
                "    expect(box, 'the quantity box should be visible').to_be_visible()",
                "    start = _number(box)",
                "    page.locator(FEATURES['plus']).first.click()",
                "    page.wait_for_timeout(500)",
                "    assert _number(box) == start + 1, f'+ should raise the quantity from {start:g} to {start + 1:g}, it shows {_number(box):g}'",
                "    page.locator(FEATURES['minus']).first.click()",
                "    page.wait_for_timeout(500)",
                "    assert _number(box) == start, f'- should lower the quantity back to {start:g}, it shows {_number(box):g}'",
                "    low = min(float(box.get_attribute('min') or 1), start)  # the box's own minimum (a quantity: 1)",
                "    for _ in range(int(start - low) + 1):  # go down to the minimum and press - once more",
                "        page.locator(FEATURES['minus']).first.click()",
                "        page.wait_for_timeout(300)",
                "    assert _number(box) >= low, f'- must stop at the minimum {low:g}, the quantity shows {_number(box):g}'",
                "",
            ]
        elif cid == "internal_links_work":
            out += [
                "def test_internal_links_work(page):",
                f'    """{title}"""',
                "    page.goto(URL)",
                "    broken = []",
                "    for href in LINKS:",
                "        try:",
                "            r = page.request.get(href, timeout=15000)",
                "            if r.status >= 400:",
                '                broken.append(f"{r.status}  {href}")',
                "        except Exception as e:",
                '            broken.append(f"ERROR  {href}  ({str(e)[:80]})")',
                '    assert not broken, "Broken links:\\n" + "\\n".join(broken)',
                "",
            ]
        elif cid == "images_load":
            out += [
                "def test_images_load(page):",
                f'    """{title}"""',
                "    page.goto(URL)",
                "    page.wait_for_load_state('networkidle')",
                "    broken = page.evaluate(\"[...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.src).map(i => i.src)\")",
                '    assert not broken, "Broken images:\\n" + "\\n".join(broken)',
                "",
            ]
        elif cid.endswith("_required_validation") and cid.split("_")[0] in forms:
            f = forms[cid.split("_")[0]]
            out += [
                f"def test_{cid}(page):",
                f'    """{title}"""',
                "    page.goto(URL)",
                "    _settle(page)",
                f"    open_path(page, {opener_path(page, f['selector'], f.get('revealed_by'))!r}, {f['fields'][0]['selector']!r})",
                f"    form = page.locator({f['selector']!r}).first",
                "    for box in form.locator('input:not([type=hidden]):not([type=checkbox]):not([type=radio])'",
                "                            ':not([type=submit]):not([type=button]), textarea').all():",
                "        try:",
                "            box.fill('')  # really empty (a profile form comes filled in: sending it would save it)",
                "        except Exception:",
                "            pass",
                "    before, start = page.evaluate(LINES_JS), page.url",
                f"    submit = {_submit_locator(f)}",
                "    submit.evaluate(APPROVE_JS)  # planned: an EMPTY form is sent, the website must refuse it (test env.)",
                "    submit.click()",
                "    refused, how = _validation_shown(page, form, before)",
                "    left = page.url.split('#')[0].rstrip('/') != start.split('#')[0].rstrip('/')",
                "    assert refused, (f'Empty form was accepted: the website went on to {page.url} without an error message'",
                "                     if left else 'Empty form: no error message was shown (the form stayed on the page, '",
                "                                  'but nothing tells the visitor what is missing)')",
                "",
            ]
        elif cid.endswith("_invalid_email") and cid.split("_")[0] in forms:
            f = forms[cid.split("_")[0]]
            email = next(fl for fl in f["fields"] if fl["type"] == "email")
            email_sel = email["selector"] or f"{f['selector']} >> input[type=email]"
            out += [
                f"def test_{cid}(page):",
                f'    """{title}"""',
                "    page.goto(URL)",
                "    _settle(page)",
                f"    open_path(page, {opener_path(page, f['selector'], f.get('revealed_by'))!r}, {f['fields'][0]['selector']!r})",
                f"    form = page.locator({f['selector']!r}).first",
                f"    field = page.locator({email_sel!r}).first",
                "    field.fill('not-an-email')",
                "    before = page.evaluate(LINES_JS)",
                f"    submit = {_submit_locator(f)}",
                "    submit.evaluate(APPROVE_JS)  # planned: a wrong email is sent, the website must refuse it (test env.)",
                "    submit.click()",
                "    is_valid = field.evaluate('el => el.checkValidity()') if field.count() else True",
                "    refused, how = (True, 'browser validation') if not is_valid else _validation_shown(page, form, before)",
                '    assert refused, "Invalid email \'not-an-email\' was accepted (no error message, the box is not marked invalid)"',
                "",
            ]
        elif cid.startswith("maxlength_") and cid in inputs:
            i = inputs[cid]
            out += [
                f"def test_{cid}(page):",
                f'    """{title}"""',
                "    page.goto(URL)",
                f"    field = page.locator({i['selector']!r}).first",
                f"    field.fill('a' * {i['maxlength'] + 10})",
                f"    assert len(field.input_value()) <= {i['maxlength']}, 'Field accepted more than max length'",
                "",
            ]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- agent

def _step_name(step: dict) -> str:
    cid = _ident(step["id"])
    return "button_click" if cid == "buttons_click" else cid


def steps_module(page: dict, steps: list[dict]) -> str:
    """Everything that can be done on one page, as step functions (step_<id>) - each called by its own test in
    test_checks.py."""
    code = template_script(page, steps, as_steps=True)
    code = code.replace(f'"""Auto-generated tests for {page["url"]}"""',
                        f'"""Steps for {page["url"]} - each one is a focused test of test_checks.py."""', 1)
    return re.sub(r"^def test_", "def step_", code, flags=re.M)


CART_GROUP = '@pytest.mark.xdist_group("cart")  # changes the cart: one after another, never at the same time'
CHANGES_CART = ("add_to_cart",)  # (checks whose step adds to the cart)


def checks_script(checks: list[dict], modules: dict[str, str]) -> tuple[str, list[str]]:
    """test_checks.py: one focused test per check - it calls its page's step (steps_<page>.py) and has its OWN result
    (a failing check never fails another). Returns (code, checks that have no code)."""
    used = sorted({c["parts"][0]["page"] for c in checks})
    out = ['"""Focused tests: one feature or control of one page per test - each with its own result."""',
           "import pytest", ""] + [f"import steps_{_ident(s)}" for s in used] + ["", ""]
    missing = []
    for c in checks:
        part = c["parts"][0]
        name = _step_name(part["step"])
        m = re.search(rf"^def step_{name}\(([^)]*)\)", modules.get(part["page"], ""), re.M)
        if not m:
            missing.append(f"{c['id']}: {part['step']['title']}")
            continue
        args = ", ".join(a.strip() for a in m.group(1).split(",") if a.strip())
        out += (["@pytest.mark.guest  # as a visitor (not logged in)"] if c.get("guest") else []) \
            + ([CART_GROUP] if part["step"]["id"] in CHANGES_CART else []) + [
            f"def test_{_ident(c['id'])}({args}):",
            f'    """{c["title"].replace(chr(34), chr(39)).replace(chr(92), "/")}"""',
            f"    steps_{_ident(part['page'])}.step_{name}({args})", "", ""]
    return "\n".join(out).rstrip() + "\n", missing


JOURNEY_HELPERS = OPEN_PATH_HELPER + '\n' + FORM_TARGET_HELPER + r'''
def _settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass  # some sites never go fully idle


def _leaving(page):
    """Before a click that opens another page: mark the headings this page shows. A single-page app keeps the old
    page on screen for a moment after its address changed (and 'loaded' says nothing: no new document) - _arrived
    waits until they are gone. (practicesoftwaretesting.com: its cart came ~1.5 s after the click on the cart icon;
    the test read the product page, which also names the product.)"""
    try:
        page.evaluate("() => document.querySelectorAll('h1, h2, h3').forEach(e => { if (!e.closest("
                      "'header, nav, footer, aside, dialog, [role=dialog]')) e.setAttribute('data-qa-left', '1'); })")
    except Exception:
        pass


def _arrived(page, ms=6000):
    """The page opened by the click is shown: the headings _leaving marked are gone (a new document has none)."""
    try:
        page.wait_for_function("() => !document.querySelector('[data-qa-left]')", timeout=ms)
    except Exception:
        pass  # (the new page kept such a heading: it is read as it is)


def _key(url):
    """Which page an address is: its path + its #/route  (https://x.com/client/#/auth/login -> /client#/auth/login)."""
    rest = re.sub(r"^https?://[^/]+", "", url or "")
    path, _, frag = rest.partition("#")
    path = path.split("?")[0].rstrip("/") or "/"
    frag = frag.lstrip("!")
    return path + ("#" + frag.rstrip("/") if frag.startswith("/") else "")


# query parameters that don't pick the page: tracking, session ids, display settings
NOT_THE_PAGE = re.compile(r"^(utm_\w+|gclid|fbclid|msclkid|dclid|mc_cid|mc_eid|_ga|_gl|igshid|phpsessid|jsessionid|"
                          r"sid|sessionid|session_id|currency|language|lang|locale)$", re.I)


def _params(url):
    query = (url or "").split("#")[0].partition("?")[2]
    return {p.partition("=")[0]: p.partition("=")[2] for p in query.split("&")
            if p and not NOT_THE_PAGE.match(p.partition("=")[0])}


def _page_of(url):
    """Which page an address is, including the query that picks it: on index.php?rt=product/product&product_id=50
    every page has the same path - the query tells them apart."""
    return (_key(url), sorted(_params(url).items()))


def _same_page(actual, expected):
    """The expected page was opened: the same path / route, and the query that picks it (more may be added)."""
    got = _params(actual)
    return _key(actual) == _key(expected) and all(got.get(k) == v for k, v in _params(expected).items())


def _logged_out(page):
    """Is a login screen shown (a visible password box)?"""
    try:
        return page.locator("input[type=password]").first.is_visible()
    except Exception:
        return False


def _link(page, link):
    """The link a person would click: found by its text, else by its address. None = not visible right now.
    Several links with the same text ('Order details' once per order): the one with THIS address first."""
    rest = re.sub(r"^https?://[^/]+", "", link["href"])
    route = rest.partition("#")[2]
    by_text = [page.get_by_role("link", name=link["text"], exact=True)] if link["text"] else []
    by_href = [page.locator(f'a[href="{href}"]') for href in dict.fromkeys(
        h for h in (link["href"], rest, "#" + route if route else "",
                    "#" + link.get("section", "") if link.get("section") else "") if h)]
    try:
        shared = bool(by_text) and by_text[0].count() > 1
    except Exception:
        shared = False
    tries = by_href + by_text if shared else by_text + by_href
    for loc in tries:
        try:
            if loc.count() and loc.first.is_visible():
                # Accessibility skip links may sit outside the viewport until keyboard focus.
                if re.search(r"^skip\s+(to\s+)?", link.get("text", ""), re.I):
                    loc.first.focus(timeout=5000)
                return loc.first
        except Exception:
            continue
    return None


SECTION_JS = """id => {
    const e = document.getElementById(id) || document.getElementsByName(id)[0];
    if (!e) return 'missing';
    const r = e.getBoundingClientRect();
    return (r.top < innerHeight && r.bottom > 0) ? 'shown' : 'not shown';
}"""


def _no_new_errors(console_errors, before, what):
    new = console_errors[before:]
    assert not new, f"{what} caused JavaScript errors:\n" + "\n".join(new[:5])
''' + LOGIN_HELPER


CART_HELPERS = r'''
ROW = 'tr, li, [role=row], [class*=item i], [class*=line i], [class*=row i], [class*=product i]'
CONTROLS = 'input, button, select, [role=button], [role=spinbutton]'


def _rows_of(page, name):
    return page.locator(ROW).filter(has_text=name).filter(has=page.locator(CONTROLS))


def _cart_row(page, name):
    """The cart line of an item: the innermost row-like element with its name and a control (quantity / remove) -
    else, in a cart that only shows its lines (a table without controls), the table row with its name."""
    rows = _rows_of(page, name)
    if rows.count():
        return rows.last
    rows = page.locator('tr').filter(has_text=name)
    return rows.last if rows.count() else None


NUMBER = re.compile(r'\s*(\d[\d,]*(?:\.\d{1,2})?)\s*')
TOTAL_LABEL = re.compile(r'\s*((grand|order|cart|basket)\s+)?total\s*:?\s*', re.I)


def _cart_total(page):
    """The cart total a person reads: the last line saying 'total' with an amount, or the amount on the line after a
    line that is ONLY a total label (demoblaze shows 'Total' / '360', without a currency). A table's heading row
    'Price  Quantity  Total' is no label: the next line is the first item's (automationexercise.com: its unit price
    was read as the cart's total)."""
    lines = [l.strip() for l in page.locator('body').inner_text().split('\n') if l.strip()]
    found = None
    for n, line in enumerate(lines):
        if re.search(r'\btotal\b', line, re.I):
            nxt = lines[n + 1] if n + 1 < len(lines) else ''
            label = TOTAL_LABEL.fullmatch(line)
            amount = _money(line) if _money(line) is not None else _money(nxt) if label else None
            plain = NUMBER.fullmatch(nxt) if amount is None and label else None
            amount = float(plain.group(1).replace(',', '')) if plain else amount
            found = amount if amount is not None else found
    return found


def _line_total(row):
    """A cart line's own total (price x quantity): the amount under its 'Total' / 'Subtotal' heading, else the last of
    two or more amounts on the line (automationexercise.com: 'Rs. 500 | 2 | Rs. 1000'). None = no line total."""
    try:
        heads = row.locator('xpath=ancestor::table[1]//th').all_inner_texts()
        col = next((n for n, h in enumerate(heads) if re.fullmatch(r'\s*(sub\s*-?\s*)?total\s*', h, re.I)), None)
        cells = row.locator('td, th')
        if col is not None and cells.count() > col and _money(cells.nth(col).inner_text()) is not None:
            return _money(cells.nth(col).inner_text())
        amounts = [float(m.group(1).replace(',', '')) for m in MONEY.finditer(row.inner_text())]
        return amounts[-1] if len(amounts) >= 2 else None
    except Exception:
        return None


def _totals(page, name):
    """(the cart total, the line's own total) as the cart shows them now."""
    row = _cart_row(page, name)
    return _cart_total(page), (_line_total(row) if row is not None else None)


def _total_follows(before, after, unit, what):
    """One more item: the cart total goes up by its price - in a cart without a total, the line's own total."""
    (t0, l0), (t1, l1) = before, after
    if t0 is not None and t1 is not None:
        assert abs((t1 - t0) - unit) < 0.01, f"{what} should add {unit:g} to the cart total, it went {t0:g} -> {t1:g}"
        return f'the cart total follows the quantity ({t0:g} -> {t1:g})'
    assert l0 is not None and l1 is not None, f"{what}: the cart shows no total - not for the cart, not for the line"
    assert abs((l1 - l0) - unit) < 0.01, f"{what} should add {unit:g} to the line's total, it went {l0:g} -> {l1:g}"
    return f"the line's total follows the quantity ({l0:g} -> {l1:g})"


def _line_price(row):
    """The price of a cart line: an amount with its currency, else the plain number under the table's 'Price'
    heading (demoblaze: '360')."""
    try:
        if _money(row.inner_text()) is not None:
            return _money(row.inner_text())
        heads = row.locator('xpath=ancestor::table[1]//th').all_inner_texts()
        col = next((n for n, h in enumerate(heads) if re.fullmatch(r'\s*(unit\s+)?price\s*', h, re.I)), None)
        cells = row.locator('td, th')
        m = NUMBER.fullmatch(cells.nth(col).inner_text()) if col is not None and cells.count() > col else None
        return float(m.group(1).replace(',', '')) if m else None
    except Exception:
        return None


def _approve(loc):
    """This one click is part of the test's plan (removing the line it added itself): the sandbox lets it through."""
    loc.evaluate("e => e.setAttribute('data-qa-approved', '1')")  # (only on a test / staging environment)


def _note(text):
    """A step that could not be done on this website: said next to the result in the report, never hidden
    (the conftest reads these lines from the test's output)."""
    print(f'[qa-note] {text}')


QTY_BOX = ('input[type=number], [role=spinbutton], input[name*=qty i], input[name*=quantity i], '
           'input[aria-label*=quantity i], input[class*=qty i]')
QTY_SELECT = ('select[name*=qty i], select[name*=quantity i], select[id*=qty i], select[id*=quantity i], '
              'select[class*=qty i], select[class*=quantity i], select[aria-label*=qty i], select[aria-label*=quantity i]')


def _qty_list(row):
    """The line's quantity LIST (<select>): one named for the quantity, or the only list of a line that says 'Qty'."""
    pick = row.locator(QTY_SELECT)
    if not pick.count() and row.locator('select').count() == 1 and re.search(r'\b(qty|quantity)\b', row.inner_text(), re.I):
        pick = row.locator('select')
    return pick if pick.count() else None


def _line_qty(row):
    """The quantity of a cart line: its quantity box or list (its CHOSEN value - the text of a list holds every choice:
    'Qty: 1 2 3 ...' would always read 1), else a 'Qty: 2' text, a quantity cell (<td class="qty">2</td>) or the
    cell under the table's 'Qty' / 'Quantity' heading. None = it can't be read."""
    box = row.locator(QTY_BOX)
    try:
        if box.count():
            return float(box.first.input_value() or 0)
        pick = _qty_list(row)
        if pick is not None:
            m = re.search(r'\d+', pick.first.input_value() or '') or re.search(r'\d+', pick.first.evaluate(
                's => s.selectedIndex >= 0 ? s.options[s.selectedIndex].text : ""'))
            return float(m.group(0)) if m else None
        m = re.search(r'(?:qty|quantity)\D{0,3}(\d+)', row.inner_text(), re.I)
        if m:
            return float(m.group(1))
        cell = row.locator('[class*=qty i], [class*=quantity i]')
        m = re.fullmatch(r'\s*(\d+)\s*', cell.first.inner_text()) if cell.count() else None
        if m:
            return float(m.group(1))
        heads = row.locator('xpath=ancestor::table[1]//th').all_inner_texts()
        col = next((n for n, h in enumerate(heads) if re.search(r'\b(qty|quantity)\b', h, re.I)), None)
        cells = row.locator('td, th')
        if col is not None and cells.count() > col:
            m = re.fullmatch(r'\s*(\d+)\s*', cells.nth(col).inner_text())
            return float(m.group(1)) if m else None
        return None
    except Exception:
        return None


def _one_more(row):
    """Raise the line's quantity by one: its '+' button, else its quantity box or list (with the cart's 'Update'
    button: that one click is planned - it changes only the line this test added)."""
    plus = row.get_by_role('button', name=re.compile(r'^\s*[+＋]\s*$|increase|increment|plus', re.I))
    if plus.count():
        plus.first.click(timeout=5000)
        return True
    box, pick = row.locator(QTY_BOX), _qty_list(row)
    if not box.count() and pick is not None:  # a quantity list: choose the next number (its value or its label)
        box = pick
        box.first.select_option(str(int(_line_qty(row) or 1) + 1), timeout=5000)
    elif box.count():
        box.first.fill(str(int(float(box.first.input_value() or 1)) + 1))
        box.first.dispatch_event('change')
        box.first.blur()
    if box.count():
        update = box.first.locator('xpath=ancestor::form[1]').locator(
            'button, input[type=submit]').filter(has_text=re.compile(r'update|recalculate|refresh', re.I))
        if not update.count():
            update = box.first.locator('xpath=ancestor::form[1]').locator(
                'input[type=submit][value*=pdate i], button[title*=pdate i]')
        if update.count():
            _approve(update.first)
            update.first.click(timeout=5000)
        return True
    return False


REMOVE_ICON = ('i[class*=times], i[class*=trash], i[class*=close], i[class*=remove], i[class*=delete], '
               'svg[class*=trash], svg[class*=close], svg[class*=remove], svg[class*=delete]')
REMOVE_CTL = ('[class*=delete i], [class*=remove i], [class*=trash i], [aria-label*=remove i], [aria-label*=delete i], '
              '[title*=remove i], [title*=delete i]')


def _shown_rows(page, name):
    """How many lines of this item the cart SHOWS (a removed line may only be hidden by the page's script)."""
    rows = _rows_of(page, name)
    return sum(1 for n in range(rows.count()) if rows.nth(n).is_visible())


def _remove_own(page, name):
    """Remove the cart line this test added (cleanup), and check that line is gone (the cart may hold the same item
    more than once, e.g. in another size). Its remove control may say so ('Remove'), or only show an icon - a cross
    or a trash can (automationexercise.com: <a class="cart_quantity_delete"><i class="fa fa-times">)."""
    row = _cart_row(page, name)
    if row is None:
        return
    rm = row.get_by_role('button', name=re.compile(r'remove|delete|trash|×|✕|✖', re.I))
    if not rm.count():
        rm = row.locator('a').filter(has_text=re.compile(r'remove|delete', re.I))
    if not rm.count():
        rm = row.locator(f'a:is({REMOVE_CTL}), button:is({REMOVE_CTL}), [role=button]:is({REMOVE_CTL})')
    if not rm.count():
        rm = row.locator('a, button, [role=button]').filter(has=page.locator(REMOVE_ICON))
    if not rm.count():
        _note(f"the cart line of '{name}' has no remove control that could be found: removing was not tested")
        return
    lines = _shown_rows(page, name)
    _approve(rm.first)
    rm.first.click(timeout=5000)
    for _ in range(10):  # (the page's script takes the line out: up to 5 s)
        page.wait_for_timeout(500)
        if _shown_rows(page, name) < lines:
            break
    _settle(page)
    assert _shown_rows(page, name) < lines, f"'Remove' did not take '{name}' out of the cart"
    _step_ok(f"removing '{name}' took it out of the cart")
'''


def _journey_test(c: dict) -> list[str]:
    """The code of one journey test (see test_design.builtin_journeys)."""
    j, kind = c["spec"], c["journey"]
    name = _ident(c["id"])
    head = (["@pytest.mark.guest  # starts as a visitor (not logged in)"] if c.get("guest") else []) \
        + ([CART_GROUP] if kind in ("shop", "product") else []) + [
        f"def test_{name}(page, console_errors{', qa_login' if kind == 'login' else ''}):",
        f'    """{c["title"].replace(chr(34), chr(39)).replace(chr(92), "/")}"""',
        f"    J = {pformat(j, width=100, sort_dicts=False)}".replace("\n", "\n        "),
    ]
    if kind == "login":
        body = [
            "    page.goto(J['url'])",
            "    _settle(page)",
            "    errors_before = len(console_errors)",
            "    assert _sign_in(page, J, qa_login[0], qa_login[1]), (",
            "        'The website refused the test account before asking for its password')",
            "    page.wait_for_timeout(1000)",
            "    _settle(page)",
            "    assert not _logged_out(page), 'Login with the test account did not work: the login form is still shown'",
            "    lost = []",
            "    for p in J['after']:",
            "        page.goto(p['url'])",
            "        _settle(page)",
            "        if _logged_out(page):",
            "            lost.append(f\"'{p['name']}' ({p['url']}) sent me back to the login page\")",
            "    assert not lost, 'The login did not hold:\\n' + '\\n'.join(lost)",
            "    _no_new_errors(console_errors, errors_before, 'Logging in and using the app')",
        ]
    elif kind == "shop":
        body = [
            "    page.goto(J['url'])",
            "    _settle(page)",
            "    errors_before = len(console_errors)",
            "    if J['search']:",
            "        box = page.locator(J['search']).first",
            "        expect(box, 'the search box should be visible').to_be_visible()",
            "        box.fill(J['word'])",
            "        _submit_search(page, box)",
            "        page.wait_for_timeout(1500)",
            "        _settle(page)",
            "        if not _item_landing(page, J['word'], J.get('item_pages')):  # (else: the page of its only match)",
            "            names = _listed(page, False, J.get('hints')).get('names') or []  # (the results - not the menus)",
            "            assert any(J['word'].lower() in n.lower() for n in names) or (",
            "                not names and J['word'].lower() in page.evaluate(MAIN_TEXT_JS).lower()), (",
            "                f\"searching '{J['word']}' should list it: the results are {names[:6]}\")",
            "    add = page.locator(J['add']).first",
            "    expect(add, f\"the '{J['add_text']}' button should be visible\").to_be_visible()",
            "    before = page.locator('body').inner_text()",
            "    add.click(timeout=5000)",
            "    page.wait_for_timeout(1500)",
            "    assert page.locator('body').inner_text() != before, f\"Nothing changed after clicking '{J['add_text']}'\"",
            "    word = J['word'].lower()",
            "    seen_before, where_before = page.locator('body').inner_text().lower().count(word), _page_of(page.url)",
            "    page.locator(J['cart']).first.click(timeout=5000)",
            "    page.wait_for_timeout(1500)",
            "    _settle(page)",
            "    body = page.locator('body').inner_text().lower()",
            "    if word:  # the cart opened (more places show the item, or a cart page) and it lists the item",
            "        assert word in body and (body.count(word) > seen_before or _page_of(page.url) != where_before), (",
            "            f\"The cart does not show '{J['word']}' after adding it\")",
            "    else:",
            "        assert _page_of(page.url) != where_before or body != before.lower(), \"Clicking the cart showed nothing\"",
            "    _no_new_errors(console_errors, errors_before, 'Shopping')",
        ]
    elif kind == "product":
        # every step is VERIFIED (and written down: _step_ok) - a step that can't be verified fails the journey,
        # except the ones a website may not offer (said next to the result: _note)
        body = [
            "    page.goto(J['url'])",
            "    _settle(page)",
            "    errors_before = len(console_errors)",
            "    if J['search']:  # 1) search a known product",
            "        box = page.locator(J['search']).first",
            "        expect(box, 'the search box should be visible').to_be_visible()",
            "        box.fill(J['word'])",
            "        _submit_search(page, box)",
            "        page.wait_for_timeout(1000)",
            "        _settle(page)",
            "    landed = _item_landing(page, J['word'], J.get('item_pages')) if J['search'] else ''",
            "    if landed:  # 2+3) the shop opened the page of its only match (no list of results): found, and opened",
            "        picked, price = landed, None",
            "        _step_ok(f\"the search opened the page of its only match, '{landed}'\")",
            "    else:",
            "        found = _listed(page, hints=J.get('hints'))  # 2) it is in the RESULTS (the item cards - not the menus)",
            "        names = found.get('names') or []",
            "        assert names, 'The list shows no items' + (f\" after searching '{J['word']}'\" if J['search'] else '')",
            "        pick = next((n for n, x in enumerate(names) if J['word'].lower() in x.lower()), None) if J['search'] else 0",
            "        assert pick is not None, f\"Searching '{J['word']}' did not list an item named with it: {names[:6]}\"",
            "        picked, price, list_url = names[pick], _money(found['cards'][pick]), page.url",
            "        _step_ok(f\"'{picked}' is found in the results\" if J['search'] else f\"the list shows '{picked}'\")",
            "        page.locator(f'[data-qa-item=\"{pick}\"]').first.click(timeout=10000)  # 3) open it: its identity",
            "        _settle(page)",
            "        assert _page_of(page.url) != _page_of(list_url), f\"Clicking '{picked}' did not open its page\"",
            "    shown, item_url = _product_name(page, picked), page.url",
            "    assert _same_name(picked, shown), f\"'{picked}' was clicked, its page shows '{shown}'\"",
            "    _step_ok(f\"its page opened and shows its name '{shown}'\")",
            "    before = None",
            "    if J.get('cart_url'):  # (what the cart holds already: a test account's cart may not be empty)",
            "        page.goto(J['cart_url'])",
            "        _settle(page)",
            "        row = _cart_row(page, shown[:40]) or _cart_row(page, picked[:40])",
            "        before = _line_qty(row) if row is not None else 0.0",
            "        page.goto(item_url)",
            "        _settle(page)",
            "    chosen = _choose_options(page, J['add'])  # 4) a valid value for every option it needs",
            "    if chosen:",
            "        _step_ok('a valid option was chosen: ' + ', '.join(chosen))",
            "    add = page.locator(J['add']).first  # 5) add it to the cart",
            "    expect(add, f\"the '{J['add_text']}' button should be visible\").to_be_visible()",
            "    said = _messages(page)",
            "    add.click(timeout=5000)",
            "    page.wait_for_timeout(1000)",
            "    _settle(page)",
            "    _judge(page, said, f\"Clicking '{J['add_text']}'\", J.get('guest'))  # an error message fails it",
            "    _step_ok(f\"'{J['add_text']}' added it without an error message\")",
            "    _leaving(page)",
            "    if J.get('cart_url'):  # 6) the cart lists it, with its quantity",
            "        page.goto(J['cart_url'])",
            "    else:",
            "        page.locator(J['cart']).first.click(timeout=10000)",
            "    _arrived(page)",
            "    _settle(page)",
            "    row = None",
            "    for _ in range(10):  # (a cart shows its lines when its data has arrived: up to 5 s)",
            "        row = _cart_row(page, shown[:40]) or _cart_row(page, picked[:40])",
            "        if row is not None:",
            "            break",
            "        page.wait_for_timeout(500)",
            "    assert row is not None, f\"The cart does not list '{shown}' after adding it\"",
            "    _step_ok(f\"'{shown}' is in the cart\")",
            "    qty = _line_qty(row)",
            "    if qty is not None and before is not None:",
            "        assert qty - before == 1, f\"One '{shown}' was added: its quantity in the cart went {before:g} -> {qty:g}\"",
            "        _step_ok(f'its quantity in the cart is right ({before:g} -> {qty:g})')",
            "    else:",
            "        _note(f\"the quantity of '{shown}' in the cart could not be read\")",
            "    unit = _line_price(row)  # 7) its price, and the total follows the quantity",
            "    if price is not None and unit is not None:",
            "        assert abs(unit - price) < 0.01, f\"The cart shows '{shown}' for {unit:g}, the list showed {price:g}\"",
            "        _step_ok(f'its price in the cart is the price the list showed ({unit:g})')",
            "    if J.get('change_cart'):  # (test environment: the cart of the test account)",
            "        sums0 = _totals(page, shown[:40])  # (the cart's total - in a cart without one, the line's own total)",
            "        assert sums0 != (None, None), 'The cart shows no total - not for the cart, not for the line'",
            "        if unit is not None and _one_more(row):",
            "            page.wait_for_timeout(1000)",
            "            _settle(page)",
            "            _step_ok(_total_follows(sums0, _totals(page, shown[:40]), unit, f\"One more '{shown}'\"))",
            "        elif unit is not None:  # (a cart without quantity controls: one more, added again on its own page)",
            "            page.goto(item_url)",
            "            _settle(page)",
            "            _choose_options(page, J['add'])",
            "            page.locator(J['add']).first.click(timeout=5000)",
            "            page.wait_for_timeout(1000)",
            "            _settle(page)",
            "            _leaving(page)",
            "            if J.get('cart_url'):",
            "                page.goto(J['cart_url'])",
            "            else:",
            "                page.locator(J['cart']).first.click(timeout=10000)",
            "            _arrived(page)",
            "            _settle(page)",
            "            for _ in range(10):  # (the cart's lines and total come with its data)",
            "                if _cart_row(page, shown[:40]) is not None:",
            "                    break",
            "                page.wait_for_timeout(500)",
            "            _step_ok(_total_follows(sums0, _totals(page, shown[:40]), unit,",
            "                                   f\"One more '{shown}' (added again on its page)\"))",
            "        else:  # (no price to compare with: that step could not be done - said in the report)",
            "            _note(f\"the cart shows no price for '{shown}': the total step was not possible\")",
            "        if not before:",
            "            _remove_own(page, shown[:40])  # remove it again: it must be gone (the line this test added)",
            "    # (checkout / pay is never clicked: a protected action)",
            "    _no_new_errors(console_errors, errors_before, 'The shopping journey')",
        ]
    elif kind == "orders":
        body = [
            "    page.goto(J['url'])",
            "    _settle(page)",
            "    errors_before = len(console_errors)",
            "    link = _link(page, {'href': J['href'], 'text': J['name']})",
            "    assert link is not None, f\"The order link '{J['name']}' is not on the page\"",
            "    link.click(timeout=10000)",
            "    _settle(page)",
            "    assert _same_page(page.url, J['href']), f\"The order link opened {page.url} instead of {J['href']}\"",
            "    assert not _logged_out(page), 'Opening the order sent me back to the login page'",
            "    # (a heading of any level: an order page may have only <h4> 'Billing address' ...)",
            "    expect(page.get_by_role('heading').first, 'the order page should have a heading').to_be_visible()",
            "    detail = page.url",
            "    for sub in J.get('subs', []):  # the order's own pages (e.g. 'Track shipment'): each one opens",
            "        page.goto(detail)",
            "        _settle(page)",
            "        link = _link(page, sub)",
            "        assert link is not None, f\"'{sub['text']}' is not on the order page\"",
            "        link.click(timeout=10000)",
            "        _settle(page)",
            "        assert _key(page.url).startswith(_key(detail).rstrip('/') + '/'), (",
            "            f\"'{sub['text']}' opened {page.url}, not a page of this order\")",
            "        assert not _logged_out(page), f\"'{sub['text']}' sent me back to the login page\"",
            "        expect(page.get_by_role('heading').first, f\"'{sub['text']}' should show a page with a heading\").to_be_visible()",
            "    _no_new_errors(console_errors, errors_before, 'Opening an order')",
        ]
    elif kind == "form":
        body = [
            "    page.goto(J['url'])",
            "    _settle(page)",
            "    if J.get('openers'):",
            "        open_path(page, J['openers'], J.get('form'))",
            "    errors_before = len(console_errors)",
            "    fill_input_check(page, J)",
            "    # (the form is NOT sent - no account is created, no message is sent)",
            "    _no_new_errors(console_errors, errors_before, 'Filling the form')",
        ]
    else:  # navigate
        body = [
            "    page.goto(J['start'])",
            "    _settle(page)",
            "    errors_before = len(console_errors)",
            "    bad = []",
            "    page.on('response', lambda r: bad.append(f'HTTP {r.status}  {r.url}')",
            "            if r.request.is_navigation_request() and r.status >= 400 else None)",
            "    opened, problems = 0, []",
            "    for link in J['links']:",
            "        if _page_of(page.url) != _page_of(J['start']):",
            "            page.goto(J['start'])",
            "            _settle(page)",
            "        el = _link(page, link)",
            "        if el is None:",
            "            continue  # (in a menu that is closed right now - its page is still checked by 'Every page opens')",
            "        tabs = len(page.context.pages)",
            "        el.click(timeout=5000)",
            "        page.wait_for_timeout(800)",
            "        _settle(page)",
            "        if link.get('section'):  # a link to a part of a page: it must scroll there",
            "            page.wait_for_timeout(700)  # (smooth scrolling)",
            "            where = page.evaluate(SECTION_JS, link['section'])",
            "            if where == 'missing':",
            "                problems.append(f\"'{link['text']}' points to #{link['section']}, but the page has no such part\")",
            "            elif where == 'not shown':",
            "                problems.append(f\"'{link['text']}' did not scroll to its part of the page (#{link['section']})\")",
            "            else:",
            "                opened += 1",
            "            continue",
            "        now = page.url",
            "        if len(page.context.pages) > tabs:  # it opened in a new tab",
            "            new = page.context.pages[-1]",
            "            new.wait_for_load_state()",
            "            now = new.url",
            "            new.close()",
            "        if not _same_page(now, link['to']):",
            "            problems.append(f\"'{link['text']}' opened {now} instead of {link['to']}\")",
            "        elif J['logged_in'] and _logged_out(page):",
            "            problems.append(f\"'{link['text']}' sent me back to the login page\")",
            "        else:",
            "            opened += 1",
            "    assert opened or problems, 'None of the menu links could be clicked (all hidden)'",
            "    assert not problems, 'Moving through the website:\\n' + '\\n'.join(problems)",
            "    assert not bad, 'Error pages while moving through the website:\\n' + '\\n'.join(bad[:5])",
            "    _no_new_errors(console_errors, errors_before, 'Moving through the website')",
        ]
    return head + body + ["", ""]


# What the website said: its message elements (toast, status line, alert role ...) + the browser's own message boxes
# ("alert: Product added." - written down by the conftest; the same text twice on one page is numbered, so the second
# one is still a new message). Used by the built-in tests (RESULT_HELPERS) and by the AI's tests (_said).
MESSAGES_JS = """() => [...new Set([...document.querySelectorAll('[role=alert], [role=status], [aria-live], ' +
  '[class*=toast i], [class*=alert i], [class*=snack i], [class*=notif i], [class*=msg i], [class*=message i], ' +
  '[class*=error i], [class*=success i]')].filter(e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
  return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'
    && !e.closest('.vjs-control, .vjs-control-bar, [role=timer]'); })
  .map(e => (e.innerText || '').trim()).filter(t => t && t.length < 200))]
  .concat((window.__qaDialogs || []).map((m, n) => n ? m + ' (' + (n + 1) + ')' : m))"""

# the helper the AI's tests (test_flows_ai.py) get: what the website said so far - also in an alert box
SAID_HELPER = '''

MESSAGES_JS = """''' + MESSAGES_JS + '''"""


def _said(page):
    """Every message the website showed so far: its message boxes and the browser's alert boxes ('alert: ...')."""
    page.wait_for_timeout(500)
    return page.evaluate(MESSAGES_JS)
'''

RESULT_HELPERS = r'''
# What the website SAYS after an action decides, in its own words: an error message fails the test; a visitor who is
# asked to sign in is "needs a test account" (not passed, not a bug). Prices and item cards are read like a person.
MESSAGES_JS = """''' + MESSAGES_JS + r'''"""
# a search box's own button: the nearest button around the box that says (or shows an icon for) search / submit / find
SEARCH_BUTTON_JS = """box => { let n = box;
  const said = e => [e.id, e.getAttribute('class'), e.getAttribute('aria-label'), e.getAttribute('title'), e.innerText,
                     e.value, ...[...e.querySelectorAll('i, svg, img')].map(i => i.getAttribute('class') || i.alt)].join(' ');
  for (let k = 0; k < 4 && n.parentElement; k++) {
    n = n.parentElement;
    const b = [...n.querySelectorAll('button, input[type=submit], input[type=button], [role=button], a')]
      .find(e => e !== box && e.offsetParent !== null && /search|submit|find/i.test(said(e)));
    if (b) { b.setAttribute('data-qa-search', '1'); return true; }
  }
  return false; }"""


def _submit_search(page, box):
    """Send a search like a person: Enter - and when that changes nothing (a search box outside a form only searches
    with its button: automationexercise.com), the search button next to the box."""
    url0, text0 = page.url, page.locator('body').inner_text()
    box.press('Enter')
    page.wait_for_timeout(1200)
    if page.url != url0 or page.locator('body').inner_text() != text0:
        return
    if box.evaluate(SEARCH_BUTTON_JS):
        page.locator('[data-qa-search="1"]').first.click(timeout=5000)
        page.wait_for_timeout(800)
# the card of each matched link: the nearest element that repeats with its siblings (never the whole page: a
# <body class="product-category"> is no card)
CARDS_JS = """sel => [...new Set([...document.querySelectorAll(sel)].map(e => {
  const sig = x => x.tagName + '|' + ((x.classList && x.classList[0]) || '');
  for (let a = e, n = 0; a && a.parentElement && n < 7 && !/^(BODY|HTML|MAIN|FORM)$/.test(a.tagName); a = a.parentElement, n++)
    if ([...a.parentElement.children].filter(c => sig(c) === sig(a)).length >= 2) return a;
  return e; }))].map(c => (c.innerText || '').trim())"""
# the page's list of items, as the explorer reads it (backend/agents/discovery.py ITEM_LIST_FN), and the text of a
# page's own content without the website's menus, header and footer (MAIN_TEXT_JS)
ITEMS_JS = ''' + repr(ITEMS_JS) + r'''
MAIN_TEXT_JS = ''' + repr(MAIN_TEXT_JS) + r'''
NONE_FOUND = re.compile(r"\b(no (products?|results?|items?|matches|entries)|nothing (was )?found|0 (results|items|"
                        r"products)|(did not|didn't|does not|doesn't) match|no .{0,40}match|could ?n[o']t find|"
                        r"not found)\b", re.I)


def _listed(page, mark=True, hints=None):
    """The page's list of items, as a person reads it - the item cards, never a menu, the breadcrumb or the header:
    {'names', 'cards', 'hrefs', 'selector'} ({} = no list). Each card's main link gets [data-qa-item=<n>]. `hints`:
    the website's item lists as exploring found them (so a search with 1 or 2 results is read too)."""
    try:
        return page.evaluate(ITEMS_JS, {'mark': mark, 'hints': list(hints or [])}) or {}
    except Exception:
        return {}


def _said_none(page):
    """Does the page say that nothing was found ('There is no product that matches ...', 'No results')?"""
    try:
        return bool(NONE_FOUND.search(page.locator('body').inner_text()))
    except Exception:
        return False


LINK_TEXTS_JS = "() => [...document.querySelectorAll('a[href]')].map(a => [a.href, (a.textContent || '').replace(/\\s+/g, ' ').trim()])"


def _mentions(page, href, word, items=None):
    """Does an item's own page mention the word - in its name, description, tags or details (also a hidden tab), not
    in the website's header, menus or footer (a cart menu that lists another item proves nothing), and not in the
    names of OTHER items it links to (a 'Bestsellers' list beside it)? `items`: the address patterns of item pages."""
    try:
        page.goto(href)
        _settle(page)
        text = page.evaluate(MAIN_TEXT_JS)
        here = page.url.split('#')[0]
        for link, name in (page.evaluate(LINK_TEXTS_JS) if items else []):
            if name and link.split('#')[0] != here and _item_address(link, items):
                text = text.replace(name, ' ')
        return word.lower() in text.lower()
    except Exception:
        return True  # (its page could not be read: no evidence against the result)


def _item_address(url, items):
    """Is this the address of one of the website's item pages ('/product/{id}', '/index.php?rt=product/product&{id}':
    the patterns exploring found)?"""
    from urllib.parse import parse_qsl, urlparse
    u = urlparse(url)
    query = dict(parse_qsl(u.query))
    for pattern in items or []:
        path, _, want = pattern.partition('?')
        if not re.fullmatch(re.escape(path).replace(re.escape('{id}'), '[^/]+') + '/?', u.path or '/'):
            continue
        parts = [p.partition('=') for p in want.split('&') if p and p != '{id}']
        if all(query.get(k) == v for k, _, v in parts):
            return True
    return False


def _item_landing(page, word, items):
    """Did the search open the page of its only match (many shops skip the results list then)? Its address is one of
    the website's item pages - not the results page, which carries the search - and its name has the word. Returns
    that name ('' = no)."""
    from urllib.parse import unquote_plus
    if not word or not items or word.lower() in unquote_plus(page.url).lower() or not _item_address(page.url, items):
        return ''
    name = _product_name(page)
    return name if word.lower() in (name or '').lower() else ''


def _step_ok(text):
    """A step of a journey that was verified (the report lists them, in order; the chat shows it ticking)."""
    print(f'[qa-step] {text}')
    if hasattr(pytest, 'qa_step'):  # (the run's conftest.py: the step ticks live in the chat)
        pytest.qa_step(text, True)


def _inconclusive(reason):
    """The expected result could not be established: reported as INCONCLUSIVE with the reason - never as passed,
    never as a website bug."""
    print(f'[qa-inconclusive] {reason}')


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _same_name(a, b):
    """The same item name (any case or punctuation; a name the list shortened or cut off; or the same item CODE in
    both: 'Flight QA101' is the page of the card 'QA101 LHR -> JFK')."""
    a, b = _norm(a), _norm(b)
    if not (a and b):
        return False
    if a in b or b in a or a[:30] == b[:30]:
        return True
    code = lambda s: {w for w in s.split() if len(w) >= 3 and re.search(r'[a-z]', w) and re.search(r'[0-9]', w)}  # noqa: E731
    return bool(code(a) & code(b))


HEADING_NAME_JS = """() => {
  const ok = e => (e.offsetWidth || e.offsetHeight) && !e.closest('nav, footer, aside, dialog, [role=dialog], .modal, ' +
    '[class*=sidebar i], [id*=sidebar i], [class*=side-bar i], [class*=widget i]') &&
    !(e.closest('header') && !e.closest('main, article'));
  const hs = [...document.querySelectorAll('h2, h3, h4')].filter(ok);
  const h = hs.find(e => e.closest('[class*=product-info i], [class*=product-detail i], [class*=product_detail i], ' +
                                   '[class*=product-title i], [itemtype*=Product]')) || hs[0];
  return h ? h.innerText.trim().split('\\n')[0] : ''; }"""


def _heading_name(page):
    """The item page's main heading: its <h1>; on a page without one, the heading of its product information, else
    the first heading of its content (<h2>-<h4>, not of a menu, sidebar, footer or hidden dialog: demoblaze's
    'Samsung galaxy s6' is an <h2>, its title just 'STORE'; automationexercise.com's 'Blue Top' is the <h2> of
    .product-information - its sidebar's 'Category' <h2> comes first and was taken as the product's name)."""
    try:
        h = page.locator('h1').first
        if h.count() and h.is_visible():
            return h.inner_text(timeout=5000).strip().split('\n')[0]
        return page.evaluate(HEADING_NAME_JS)
    except Exception:
        return ''


def _product_name(page, expect=None):
    """The name the item's own page shows: its main heading (else its title). A single-page app draws the item's
    page only when its data has arrived - the click loads no new document, so 'loaded' says nothing, and the heading
    may still be the list's (practicesoftwaretesting.com: its <h1> came ~2 s after the click): it is read again, up
    to 5 s, until it is there - and, given `expect` (the name clicked), until it is that name. Then what it shows."""
    name = ''
    for _ in range(10):
        name = _heading_name(page)
        if name and (expect is None or _same_name(expect, name)):
            return name
        page.wait_for_timeout(500)
    return name or re.split(r"\s+[|\-–—:]\s+", page.title())[0].strip()


def _choose_options(page, add):
    """A valid value for every option the item needs before it can be added (size, colour ...): a 'Please select'
    box gets its first real choice, a group of choices with none picked its first one - in the add button's form
    (else the page, never its header / menus). Returns what was chosen."""
    chosen = []
    form = page.locator(add).first.locator('xpath=ancestor::form[1]')
    scope = form if form.count() else page.locator('body')
    for box in scope.locator('select').all():
        try:
            if not box.is_visible() or box.input_value() or box.evaluate("e => !!e.closest('nav, header, footer')"):
                continue
            values = [v for v in box.evaluate("e => [...e.options].filter(o => !o.disabled).map(o => o.value)") if v]
            if values:
                box.select_option(values[0])
                chosen.append(box.evaluate("e => ((e.labels && e.labels[0] && e.labels[0].innerText) || e.name || "
                                           "e.id || 'option').trim()"))
        except Exception:
            continue
    groups = {}
    for r in scope.locator('input[type=radio]').all():
        try:
            if r.is_visible() and not r.evaluate("e => !!e.closest('nav, header, footer')"):
                groups.setdefault(r.get_attribute('name') or '', []).append(r)
        except Exception:
            continue
    for name, rs in groups.items():
        if name and not any(x.is_checked() for x in rs):
            rs[0].check()
            chosen.append(name)
    return chosen
LOGIN_NEEDED = re.compile(r"\b(log ?in|sign ?in|signed in|logged in|un ?authori[sz]ed|not authori[sz]ed|session (has )?"
                          r"expired|please (log|sign)|create an account)\b", re.I)
# (whole words, as backend/observe.py: not part of a name joined by a hyphen - 'Server-Sent Events')
ERROR = re.compile(r"(?<![\w-])(error|failed|failure|could ?n[o']t|can ?not|can't|unable|invalid|not allowed|forbidden|"
                   r"denied|out of stock|unavailable|went wrong|problem|too many)(?![\w-])", re.I)
OK = re.compile(r"(?<![\w-])(added|saved|success(fully)?|updated|removed|thank(s| you)?|done|copied|subscribed|sent|"
                r"created|applied|we will|we'll|confirmed)(?![\w-])", re.I)
MONEY = re.compile(r"(?:[₹$€£]|\b(?:rs|inr|usd|eur)\.?)\s?(\d[\d,]*(?:\.\d{1,2})?)", re.I)


def _tone(text):
    if LOGIN_NEEDED.search(text or ''):
        return 'login_needed'
    if ERROR.search(text or ''):
        return 'error'
    return 'ok' if OK.search(text or '') else ''


def _messages(page):
    return page.evaluate(MESSAGES_JS)


def _new_messages(page, before, wait_ms=3000):
    """Messages the website showed since `before` (waits a little for one to appear)."""
    for _ in range(max(1, wait_ms // 500)):
        now = [m for m in _messages(page) if m not in before]
        if now:
            return now
        page.wait_for_timeout(500)
    return []


def _judge(page, before, what, guest=False):
    """After an action: an error message fails the test with the website's own words; a visitor asked to sign in is
    skipped as 'needs a test account'. Returns the new messages."""
    msgs = _new_messages(page, before)
    for m in msgs:
        tone = _tone(m)
        if tone == 'login_needed' and guest:
            pytest.skip(f"needs a test account: as a visitor the website says '{m[:120]}'")
        if tone in ('error', 'login_needed'):
            raise AssertionError(f"{what}: the website said '{m[:160]}'")
    return msgs


def _money(text):
    m = MONEY.search(text or '')
    return float(m.group(1).replace(',', '')) if m else None


def _cards(page, sel):
    return page.evaluate(CARDS_JS, sel) if sel else []


def _card_name(text):
    """The name on a card (not a badge like 'ECO', a rating letter or the price)."""
    return next((t.strip() for t in (text or '').split('\n') if len(t.strip()) >= 4
                 and re.search('[A-Za-z]{3}', t) and not MONEY.search(t)), '')


def _sort_rule(label):
    """('price' | 'name', 'asc' | 'desc') from an option's label; None when the label doesn't say the order."""
    lab = (label or '').lower()
    desc = re.search(r"high\s*(-|to|–|→|>)\s*low|descending|\bdesc\b|highest|z\s*(-|to|–|>)\s*a", lab)
    asc = re.search(r"low\s*(-|to|–|→|>)\s*high|ascending|\basc\b|lowest|cheapest|a\s*(-|to|–|>)\s*z", lab)
    if re.search(r"price|cost|cheap|expensive", lab) and (asc or desc):
        return ('price', 'desc' if desc else 'asc')
    if re.search(r"\bname\b|title|alphabet|a\s*(-|to|–|>)\s*z|z\s*(-|to|–|>)\s*a", lab):
        return ('name', 'desc' if desc else 'asc')
    return None


def _in_order(cards, rule):
    """(in that order?, the values compared): prices = the first price on each card (exact); names = the card's name,
    by its first letter (a website's own alphabet treats accents and punctuation its own way: 'L'Extrême')."""
    if rule[0] == 'price':
        keys = [k for k in (_money(c) for c in cards) if k is not None]
        return keys == sorted(keys, reverse=rule[1] == 'desc'), keys
    names = [n for n in (_card_name(c) for c in cards) if n]
    first = [re.sub(r"[^0-9a-z]", "", n.casefold())[:1] for n in names]
    return first == sorted(first, reverse=rule[1] == 'desc'), [n.casefold() for n in names]
'''

FEATURE_HELPERS = r'''
def _items(page, selector):
    """The texts of the listed items (or the whole page's text when there is no list)."""
    if selector and page.locator(selector).count():
        return page.locator(selector).all_inner_texts()
    return [page.locator("body").inner_text()]


def _cards_of(page, selector):
    """The listed item cards (their whole text: name, price ...) - by the list's address, else read again."""
    if selector and page.locator(selector).count():
        return _cards(page, selector)
    return _listed(page, False).get('cards') or []


def _open(page, href, text):
    """Click the link a person would click (else open its address)."""
    link = _link(page, {"href": href, "text": text})
    if link is not None:
        link.click(timeout=10000)
    else:
        page.goto(href)
    _settle(page)
'''

FEATURE_BODY = {
    "filter": [
        "    before = _items(page, F['items'])",
        "    if F['href']:",
        "        _open(page, F['href'], F['name'])",
        "        after = _items(page, F['items'])",
        "        lost = {k: v for k, v in _params(F['href']).items() if _params(page.url).get(k) != v}",
        "        assert not lost, f\"The filter '{F['name']}' is not applied: the page {page.url} lacks {lost}\"",
        "    else:  # tick the boxes one by one: the first can be the list already shown (e.g. the page's own category)",
        "        after = before",
        "        for sel in F.get('boxes') or [F['box']]:",
        "            box = page.locator(sel)",
        "            set_user_checked(box, True)",
        "            page.wait_for_timeout(1000)",
        "            _settle(page)",
        "            after = _items(page, F['items'])",
        "            if after != before:",
        "                break",
        "            set_user_checked(box, False)",
        "            page.wait_for_timeout(800)",
        "            _settle(page)",
        "    assert after != before, f\"Using the filter '{F['name']}' did not change the list\"",
        "    if not F['href']:  # clearing the filter (untick) shows the full list again",
        "        set_user_checked(box, False)",
        "        page.wait_for_timeout(1000)",
        "        _settle(page)",
        "        assert sorted(_items(page, F['items'])) == sorted(before), (",
        "            f\"Clearing the filter '{F['name']}' did not bring the full list back\")",
    ],
    "filter_pages": [
        "    _open(page, F['href'], F['name'])",
        "    kept = re.findall(r'[^?&=#]+=[^&#]*', F['href'].split('?', 1)[1]) if '?' in F['href'] else []",
        "    before = _items(page, F['items'])",
        "    nxt = page.locator('a[rel=next], [aria-label*=next i]').first",
        "    if not nxt.count():",
        "        nxt = page.get_by_role('link', name=re.compile(r'^(next|next page|›|»|>)$', re.I)).first",
        "    if not nxt.count():",
        "        pytest.skip('this filtered list has only one page')",
        "    nxt.click(timeout=10000)",
        "    _settle(page)",
        "    assert _items(page, F['items']) != before, 'The next page shows the same items'",
        "    lost = [k for k in kept if k not in page.url]",
        "    assert not lost, f\"Going to the next page dropped the filter: {lost} is no longer in {page.url}\"",
    ],
    "sort": [
        "    box = page.locator(F['selector']).first",
        "    expect(box, 'the sort box should be visible').to_be_visible()",
        "    before, changed, checked = _items(page, F['items']), False, []",
        "    for value, label in zip(F['options'], F.get('labels') or F['options']):",
        "        if value == page.locator(F['selector']).first.input_value():",
        "            continue",
        "        page.locator(F['selector']).first.select_option(value)",
        "        page.wait_for_timeout(800)",
        "        _settle(page)",
        "        expect(page.locator(F['selector']).first, f'option {label!r} should stay selected').to_have_value(value)",
        "        changed = changed or _items(page, F['items']) != before",
        "        rule = _sort_rule(label)",
        "        cards = _cards_of(page, F['items'])  # (the item cards - never the menus)",
        "        if rule and len(cards) >= 2:  # the label says the order: check it",
        "            ok, keys = _in_order(cards, rule)",
        "            assert ok, f\"'{label}' should sort by {rule[0]} ({rule[1]}ending), the items show: {keys[:10]}\"",
        "            checked.append(label)",
        "    assert checked or changed, f\"Choosing another order in '{F['name']}' did not change the order of the items\"",
    ],
    "pagination": [
        "    before = _items(page, F['items'])",
        "    if F.get('selector'):  # a page button (« 1 2 3 »): no address to open",
        "        page.locator(F['selector']).first.click(timeout=10000)",
        "        _settle(page)",
        "    else:",
        "        _open(page, F['href'], F['name'])",
        "    for _ in range(10):  # (a list loaded by the page's script can take a moment)",
        "        if _items(page, F['items']) != before:",
        "            break",
        "        page.wait_for_timeout(500)",
        "    assert _items(page, F['items']) != before, f\"'{F['name']}' shows the same items as the first page\"",
    ],
    "wishlist": [
        "    before, said = page.locator('body').inner_text(), _messages(page)",
        "    page.locator(F['selector']).first.click(timeout=5000)",
        "    page.wait_for_timeout(800)",
        "    _settle(page)",
        "    msgs = _judge(page, said, f\"Clicking '{F['name']}'\", F.get('guest'))  # an error message fails it",
        "    assert msgs or page.locator('body').inner_text() != before, (",
        "        f\"Clicking '{F['name']}' changed nothing on the page (no message, no count)\")",
    ],
    "quantity": [  # what the CART gets: a valid quantity, and an invalid one (refused or corrected, never taken as is)
        "    name = _product_name(page)",
        "    def in_cart():",
        "        page.goto(F['cart_url'])",
        "        _settle(page)",
        "        row = _cart_row(page, name[:40])",
        "        return _line_qty(row) if row is not None else 0.0",
        "    def add(qty):",
        "        page.goto(F['url'])",
        "        _settle(page)",
        "        _choose_options(page, F['add'])",
        "        page.locator(F['qty']).first.fill(qty)",
        "        said = _messages(page)",
        "        page.locator(F['add']).first.click(timeout=5000)",
        "        page.wait_for_timeout(1000)",
        "        _settle(page)",
        "        return _new_messages(page, said, 1500)",
        "    start = in_cart()",
        "    if start is None:",
        "        _inconclusive(f\"the cart lists '{name}', but its quantity could not be read\")",
        "        return",
        "    msgs = add('2')",
        "    bad = [m for m in msgs if _tone(m) in ('error', 'login_needed')]",
        "    if bad and _tone(bad[0]) == 'login_needed' and F.get('guest'):",
        "        pytest.skip(f\"needs a test account: as a visitor the website says '{bad[0][:120]}'\")",
        "    assert not bad, f\"Adding 2 x '{name}': the website said '{bad[0][:160]}'\" if bad else ''",
        "    got = in_cart()",
        "    assert got is not None and got - start == 2, (f\"Quantity 2 was added: the cart's quantity of '{name}' went \"",
        "                                                 f\"{start:g} -> {got if got is None else format(got, 'g')}\")",
        "    _step_ok('a valid quantity (2) reached the cart')",
        "    row = _cart_row(page, name[:40])  # its price follows the quantity: the line's total = price x quantity",
        "    unit, line = (_line_price(row), _line_total(row)) if row is not None else (None, None)",
        "    if unit is not None and line is not None:",
        "        assert abs(line - unit * got) < 0.01, (f\"{got:g} x '{name}' at {unit:g}: the cart's line total is \"",
        "                                              f\"{line:g}, not {unit * got:g}\")",
        "        _step_ok(f'the price follows the quantity: {got:g} x {unit:g} = {line:g}')",
        "    add('-1')  # an invalid quantity: refused (a message), or corrected (e.g. to 1) - never subtracted",
        "    now = in_cart()",
        "    assert now is not None and now >= got, (f\"Quantity -1 was accepted: the cart's quantity of '{name}' went \"",
        "                                           f\"{got:g} -> {now if now is None else format(now, 'g')}\")",
        "    _step_ok(f'an invalid quantity (-1) was refused or corrected ({got:g} -> {now:g})')",
        "    if start == 0:",
        "        _remove_own(page, name[:40])  # cleanup: the line this test added",
    ],
    "search": [
        "    box = page.locator(F['selector']).first",
        "    expect(box, 'the search box should be visible').to_be_visible()",
        "    bad = []",
        "    page.on('response', lambda r: bad.append(r.status)",
        "            if r.request.is_navigation_request() and r.status >= 500 else None)",
        "    box.fill('a' * 500)",
        "    _submit_search(page, box)",
        "    _settle(page)",
        "    assert not bad, f'Searching with 500 letters gave a server error (HTTP {bad[0]})'",
        "    expect(page.locator('body'), 'the page should still be shown').to_be_visible()",
    ],
}


def features_script(cases: list[dict]) -> str:
    """test_features.py: one test per feature the inspector found on a page (filter, sort, next page, wishlist,
    long search). Each test checks a fixed rule: the list changes, the order changes, other items are shown ..."""
    out = ['"""Feature tests: every feature found on the pages (filters, sorting, next page, quantity, wishlist, search),',
           'each checked against a fixed rule about what a person sees."""',
           "import re", "import pytest", "from playwright.sync_api import expect", "", JOURNEY_HELPERS, RESULT_HELPERS,
           CART_HELPERS, FEATURE_HELPERS, ""]
    for c in cases:
        out += (["@pytest.mark.guest  # a public page: tested as a visitor"] if c.get("guest") else []) \
            + ([CART_GROUP] if c["feature_kind"] in ("quantity", "wishlist") else []) + [
            f"def test_{_ident(c['id'])}(page, console_errors):",
            f'    """{c["title"].replace(chr(34), chr(39)).replace(chr(92), "/")}"""',
            f"    F = {pformat(c['spec'], width=100, sort_dicts=False)}".replace("\n", "\n        "),
            "    page.goto(F['url'])",
            "    _settle(page)",
            "    errors_before = len(console_errors)",
            *FEATURE_BODY[c["feature_kind"]],
            "    _no_new_errors(console_errors, errors_before, 'Using this feature')",
            "", ""]
    return "\n".join(out).rstrip() + "\n"


LEARNED_HELPERS = OPEN_PATH_HELPER + '\n' + FORM_TARGET_HELPER + r'''
# (the page and its open shadow roots - a web component's boxes and text are what a person sees too)
ROOTS_JS = """const roots = [document];
  for (let i = 0; i < roots.length && roots.length < 40; i++)
    roots[i].querySelectorAll('*').forEach(e => { if (e.shadowRoot) roots.push(e.shadowRoot); });"""
VALUES_JS = """() => { """ + ROOTS_JS + """
  return roots.flatMap(r => [...r.querySelectorAll('input, select, textarea')]).filter(i => !['hidden', 'password',
  'file'].includes(i.type)).map(i => (i.type === 'checkbox' || i.type === 'radio') ? String(i.checked) : i.value); }"""
SHADOW_TEXT_JS = """() => { """ + ROOTS_JS + """
  return roots.slice(1).flatMap(r => [...r.children].filter(e => !['STYLE', 'SCRIPT'].includes(e.tagName))
    .map(e => e.innerText || '')).join('\\n'); }"""


def _frames(page):
    """The page and its frames (an iframe's button changes the frame, not the page)."""
    return [f for f in page.frames if not f.is_detached() and not (f.url or '').startswith('chrome-error:')]


def _all_text(page):
    out = []
    for f in _frames(page):
        try:
            out.append(f.locator('body').inner_text(timeout=3000))
            out.append(f.evaluate(SHADOW_TEXT_JS))
        except Exception:
            pass
    return '\n'.join(out)


def _all_values(page):
    out = []
    for f in _frames(page):
        try:
            out += f.evaluate(VALUES_JS)
        except Exception:
            pass
    return out


# how a control looks: its classes (not focus / hover ones: every click focuses it) and its pressed / checked /
# expanded state
LOOK_JS = ("e => [String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className || '')"
           ".split(/\\s+/).filter(c => c && !/focus|hover|ripple/i.test(c)).sort().join(' '), "
           "...['aria-pressed', 'aria-checked', 'aria-expanded', 'aria-selected'].map(a => e.getAttribute(a))]")


def _action_locator(page, selector, name=''):
    el = page.locator(selector)
    expect(el, 'Automation target must be unique in the observed state').to_have_count(1)
    return el


def _act(page, selector, action, value=None, name=''):
    el = _action_locator(page, selector, name)
    if action == 'select':
        el.select_option(value)
        expect(el).to_have_value(value)
    elif action == 'tick':
        set_user_checked(el, True)
    else:
        el.click(timeout=5000)


def _words(text):
    return {w for w in re.findall(r'[a-z]{3,}', (text or '').lower())}


def _similar(said, learned):
    """The same kind of message: at least half of the words it said while exploring (names / numbers may differ)."""
    want = _words(learned)
    return not want or len(want & _words(said)) >= len(want) / 2


def _pattern_of(url):
    return re.sub(r'/[\w-]*\d[\w-]*(?=/|$)', '/{id}', _key(url).split('#')[0])


def _check_learned(page, console_errors, L):
    """Do the action again from a fresh page and check the effect it had while exploring."""
    page.goto(L['url'])
    _settle(page)
    path = L.get('openers')
    if path is None:  # compatibility with older saved cases
        path = [{'selector': L['opener'], 'action': 'click'}] if L.get('opener') else []
    if path:
        open_path(page, path, L['selector'])
    el = _action_locator(page, L['selector'], L.get('name') or '')
    if L['action'] != 'tick':
        expect(el, f"'{L['name']}' should be visible").to_be_visible()
        el.scroll_into_view_if_needed(timeout=5000)
    page.wait_for_timeout(300)
    said, url0, text0, values0 = _messages(page), page.url, _all_text(page), _all_values(page)
    y0 = page.evaluate('() => window.scrollY')
    if L['effect'] == 'scroll' and y0 < 150:  # (a floating 'Back to top': what it does shows only further down)
        page.evaluate('() => window.scrollTo(0, document.documentElement.scrollHeight)')
        page.wait_for_timeout(400)
        y0 = page.evaluate('() => window.scrollY')
    pics = el.evaluate(REGION_JS) if L['effect'] == 'picture' else None  # the pictures its own widget shows
    look0 = el.evaluate(LOOK_JS) if L['effect'] == 'nothing' else None
    windows0 = len(page.context.pages)
    errors_before = len(console_errors)
    _act(page, L['selector'], L['action'], L.get('value'), L.get('name') or '')
    page.wait_for_timeout(800)
    _settle(page)
    # its own look changed (practicesoftwaretesting.com's 'Compare' turns from outline to filled), or it opened a
    # window ('Sign in with Google'): a visible response too
    try:
        looks_other = look0 is not None and el.evaluate(LOOK_JS, timeout=2000) != look0
    except Exception:
        looks_other = False
    opened = page.context.pages[windows0:]
    for w in opened:
        w.close()
    msgs = _new_messages(page, said, 1500 if L['effect'] != 'message' else 3000)
    for m in msgs:
        tone = _tone(m)
        if tone == 'login_needed' and L['guest']:
            pytest.skip(f"needs a test account: as a visitor the website says '{m[:120]}'")
        assert tone not in ('error', 'login_needed'), f"'{L['name']}': the website said '{m[:160]}'"
    effect = L['effect']
    if L['tone'] in ('error', 'login_needed'):
        pass  # (a rule test: no error message - checked above)
    elif effect == 'message':
        assert msgs, f"'{L['name']}' showed no message (while exploring it said '{L['message'][:100]}')"
        assert any(_similar(m, L['message']) for m in msgs), (
            f"'{L['name']}' said {msgs[0][:100]!r}, while exploring it said {L['message'][:100]!r}")
    elif effect == 'navigates':
        assert _pattern_of(page.url) == _pattern_of(L['to']) or L['to'] in page.url, (
            f"'{L['name']}' opened {page.url} instead of {L['to']}")
    elif effect == 'value':
        assert _all_values(page) != values0, f"'{L['name']}' did not change any value"
    elif effect == 'panel':
        shown = [n for n in L['revealed'] if page.get_by_text(n, exact=False).first.is_visible()] if L['revealed'] else []
        assert shown or _all_text(page) != text0, f"'{L['name']}' did not open its panel"
    elif effect in ('text', 'list'):
        assert _all_text(page) != text0 or page.url != url0, f"'{L['name']}' changed nothing"
        if L.get('added'):  # (the text it showed while exploring - 'Total: 23' - must be shown again)
            now = _all_text(page)
            assert any(a.replace('[frame] ', '').replace('[shadow] ', '') in now for a in L['added']), (
                f"'{L['name']}' changed the page, but not to what it showed while exploring: {L['added'][:2]}")
    elif effect == 'picture':
        now = page.evaluate(PICTURES_JS) if pics is not None else None
        assert pics is not None and now not in (None, pics), f"'{L['name']}' did not show another picture"
    elif effect == 'scroll':  # ('Back to top' ...): the page moved
        moved = abs(page.evaluate('() => window.scrollY') - y0)
        assert moved >= 150, f"'{L['name']}' did not move the page (it scrolled {moved:.0f} px)"
    elif effect == 'nothing':  # a rule: something visible must happen when a control is used
        assert msgs or page.url != url0 or _all_text(page) != text0 or looks_other or opened or \
            _all_values(page) != values0 or abs(page.evaluate('() => window.scrollY') - y0) >= 150, (
            f"'{L['name']}' gave no visible response (no message, nothing changed, the page did not move)")
    _no_new_errors(console_errors, errors_before, f"Using '{L['name']}'")
'''


def learned_script(cases: list[dict]) -> str:
    """test_learned.py: every control whose effect exploring learned does it again (see test_design.learned_cases)."""
    out = ['"""What each control does: learned while exploring (the evidence), checked again here. A message, a',
           'change, a panel or a page it opened must happen again; an error message never passes; a visitor who is asked',
           'to sign in is skipped as "needs a test account"."""',
           "import re", "import pytest", "from playwright.sync_api import expect", "", JOURNEY_HELPERS, RESULT_HELPERS,
           f"REGION_JS = {REGION_JS!r}", f"PICTURES_JS = {PICTURES_JS!r}", LEARNED_HELPERS, ""]
    from ..actions import action_risk
    for c in cases:
        cart = action_risk(c["spec"].get("name"), c["spec"].get("selector")) == "test_account"
        out += (["@pytest.mark.guest  # a public page: tested as a visitor"] if c.get("guest") else []) \
            + ([CART_GROUP] if cart else []) + [
            f"def test_{_ident(c['id'])}(page, console_errors):",
            f'    """{c["title"].replace(chr(34), chr(39)).replace(chr(92), "/")}"""',
            f"    L = {pformat(c['spec'], width=100, sort_dicts=False)}".replace("\n", "\n        "),
            "    _check_learned(page, console_errors, L)",
            "", ""]
    return "\n".join(out).rstrip() + "\n"


def journeys_script(journeys: list[dict]) -> str:
    """test_journeys.py: real user journeys - each one keeps going like a person, without reloading between steps."""
    out = ['"""Real user journeys: log in and use the app, search -> add to cart -> open the cart, fill whole forms,',
           'click through the menu. Each journey is ONE test that keeps going like a person would."""',
           "import re", "import pytest", "from playwright.sync_api import expect", "", JOURNEY_HELPERS, RESULT_HELPERS,
           CART_HELPERS, ""]
    for c in journeys:
        out += _journey_test(c)
    return "\n".join(out).rstrip() + "\n"


def site_script(pages: list[dict]) -> str:
    """test_site.py: the small checks that run on EVERY page (opens, no JavaScript errors, pictures load)."""
    rows = [{"slug": _ident(p["slug"]), "url": p["url"], "guest": not p.get("auth"), "images": p.get("imageCount") or 0}
            for p in pages]
    return "\n".join([
        '"""Small checks for the whole website: every page opens, has no JavaScript errors, and its pictures load."""',
        "import pytest",
        "",
        f"PAGES = {pformat(rows, width=110)}",
        "",
        "",
        "def _params(rows):",
        "    return [pytest.param(r, id=r['slug'], marks=[pytest.mark.guest] if r['guest'] else []) for r in rows]",
        "",
        "",
        "def _settle(page):",
        "    try:",
        "        page.wait_for_load_state('networkidle', timeout=5000)",
        "    except Exception:",
        "        pass  # some sites never go fully idle",
        "",
        "",
        "@pytest.mark.parametrize('pg', _params(PAGES))",
        "def test_page_loads(page, pg):",
        '    """Every page opens"""',
        "    resp = page.goto(pg['url'])",
        "    assert resp is None or resp.status < 400, f\"{pg['url']} returned HTTP {resp.status}\"",
        "    _settle(page)",
        "    assert page.title().strip() != '', f\"{pg['url']} has no <title>\"",
        "",
        "",
        "@pytest.mark.parametrize('pg', _params(PAGES))",
        "def test_no_console_errors(page, console_errors, pg):",
        '    """No JavaScript errors on any page"""',
        "    page.goto(pg['url'])",
        "    _settle(page)",
        "    assert not console_errors, f\"JavaScript errors on {pg['url']}:\\n\" + '\\n'.join(console_errors[:10])",
        "",
        "",
        "@pytest.mark.parametrize('pg', _params([r for r in PAGES if r['images']]))",
        "def test_images_load(page, pg):",
        '    """All pictures load"""',
        "    page.goto(pg['url'])",
        "    _settle(page)",
        "    broken = page.evaluate(\"[...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.src)"
        ".map(i => i.src)\")",
        "    assert not broken, f\"Broken pictures on {pg['url']}:\\n\" + '\\n'.join(broken)",
        "",
    ])


def _llm_flows(flows: list[dict], pages: dict[str, dict]) -> str:
    """The AI writes test_flows_ai.py for its large test cases (validated; one self-repair attempt)."""
    used = [pages[s] for s in dict.fromkeys(s for f in flows for s in f["pages"]) if s in pages]
    data = json.dumps([{"page": p["slug"], "url": p["url"], "logged_in": bool(p.get("auth")),
                        "title": p.get("title"), "document_title": p.get("title"),
                        "headings": p.get("headings", []),
                        "opener_paths": {x["selector"]: opener_path(p, x["selector"], x.get("revealed_by"))
                                         for group in ("buttons", "inputs", "forms") for x in p.get(group, [])
                                         if x.get("selector") and x.get("revealed_by")},
                        "permissions": {"account_creation": settings.auto_register,
                                        "test_account_available": bool(settings.test_username and settings.test_password)},
                        "buttons": lean(p.get("buttons", [])[:30]),
                        "inputs": lean(p.get("inputs", [])[:20]), "forms": lean(p.get("forms", [])[:5]),
                        "links": [{"text": l["text"], "href": l["href"], "selector": l.get("selector")} for l in p.get("links", [])
                                  if not l.get("external")][:20],
                        "items_listed": (p.get("itemNames") or [])[:8], "observed": _observed(p),
                        **({"on_screen": on_screen(p)} if p.get("seen") else {})} for p in used],
                      indent=1)
    cases = json.dumps([{k: f[k] for k in ("id", "title", "guest", "pages", "test_data", "steps", "expected")}
                        for f in flows], indent=1)
    code = extract_code(ask_llm(load_prompt("script_generator").format(pages=data, cases=cases), system=SYSTEM,
                                agent="script_generator", page="site"))

    def problem(c: str) -> str | None:
        err = validate_script(c) or grounding_problem(c, used, settings.requirements)
        if "data-qa-approved" in c or "APPROVE_JS" in c:  # (only built-in tests may plan one protected click)
            err = err or "AI code may not mark a protected click as approved"
        gone = [f["id"] for f in flows if not re.search(rf"^\s*def test_{_ident(f['id'])}\(", c, re.M)]
        return err or (f"missing test functions: {', '.join(gone)}" if gone else None)

    err = problem(code)
    if err:  # one self-repair attempt
        code = extract_code(ask_llm(load_prompt("fix_script").format(error=err, code=code) + "\nOBSERVED PAGES (use only this evidence):\n" + data,
                                    system=SYSTEM, agent="script_generator", page="site"))
        err = problem(code)
    if err:
        raise LLMError(f"the AI's test code failed the checks: {err}")
    code = _with_said(_steady(code))
    err = problem(code)
    if err:
        raise LLMError(f"the AI's test code failed the checks: {err}")
    return code


FLOW_BATCH = 5  # the AI writes its large test cases 5 at a time: one bad answer loses 5 journeys, not all 20


def _llm_flows_in_batches(flows: list[dict], pages: dict[str, dict]) -> tuple[str, list[str], str]:
    """test_flows_ai.py for many large test cases, written FLOW_BATCH at a time and merged into one file. Returns
    (the code - '' when no batch worked, the ids of the cases whose batch failed, the last error)."""
    codes, lost, why = [], [], ""
    for i in range(0, len(flows), FLOW_BATCH):
        part = flows[i:i + FLOW_BATCH]
        try:
            codes.append(_llm_flows(part, pages))
        except LLMError as e:
            lost += [f["id"] for f in part]
            why = str(e)
            print(f"  [script-gen] the AI could not write journeys {i + 1}-{i + len(part)}: {why[:160]}")
    if not codes:
        return "", lost, why
    code = _merge_flows(codes) if len(codes) > 1 else codes[0]
    err = validate_script(code)
    if err:
        return "", [f["id"] for f in flows], f"the merged AI test code failed the checks: {err}"
    return code, lost, why


def _merge_flows(codes: list[str]) -> str:
    """Several AI answers -> one file: each import once, the `_said` helper once (added again at the end), and a
    helper or constant name an earlier answer already used gets its answer's number (two `_cart_count` may differ)."""
    imports, body, names = [], [], set()
    for n, code in enumerate(codes, start=1):
        own = set()
        for node in ast.parse(code).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("test_"):
                own.add(node.name)
            elif isinstance(node, ast.Assign):
                own |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        for name in (own & names) - {"_said", "MESSAGES_JS"}:
            code = re.sub(rf"\b{re.escape(name)}\b", f"{name}_{n}", code)
        names |= own
        lines = code.split("\n")
        for node in ast.parse(code).body:
            start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            seg = "\n".join(lines[start - 1:node.end_lineno])
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if seg not in imports:
                    imports.append(seg)
            elif isinstance(node, ast.FunctionDef) and node.name == "_said" or \
                    isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "MESSAGES_JS" for t in node.targets):
                continue  # (the helper: added once below)
            elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):  # (a docstring)
                body.append(seg)
    return _with_said("\n".join(imports) + "\n\n\n" + "\n\n\n".join(body) + "\n")


# AI code that fails for the TOOL's reasons, not the website's (practicesoftwaretesting.com, Nov 3, 2026: 7 of 10 AI
# journeys failed - none on a website bug). Made steady before it runs: only HOW an element is found or waited for
# changes, never WHAT is checked.
#   'text=Power Tools' was the menu item, the page title and a filter at once (strict mode): the first VISIBLE one
TEXT_CHECK = re.compile(r"""expect\(page\.locator\((["'])((?:text=|h[1-6]\s*,)[^"'\\>]*)\1\)\)"""
                        r"""\.(to_be_visible|not_to_be_visible|to_contain_text|to_have_text)\(""")
#   the results were counted before the search had finished: expect(...).to_have_count waits for the page
COUNT_ASSERT = re.compile(r"^(\s*)assert (page\.locator\(.+?\))\.count\(\) == (\d+)\s*(?:,\s*(.+))?$", re.M)
#   `assert True` checks nothing (and a file with one could not be repaired: the check said 'cheat')
CONST_ASSERT = re.compile(r"^(\s*)assert True\s*$", re.M)
#   to_have_count takes a number - `to_have_count(lambda c: c > 0)` crashed 3 journeys (advantageonlineshopping.com):
#   "at least one" is not_to_have_count(0)
AT_LEAST_ONE = re.compile(r"\.to_have_count\(\s*lambda\s+(\w+)\s*:\s*\1\s*(?:>\s*0|>=\s*1)\s*\)")


def _steady(code: str) -> str:
    code = TEXT_CHECK.sub(lambda m: f"expect(page.locator({m[1]}{m[2]} >> visible=true >> nth=0{m[1]})).{m[3]}(", code)
    code = COUNT_ASSERT.sub(lambda m: f"{m[1]}expect({m[2]}{', ' + m[4] if m[4] else ''}).to_have_count({m[3]})", code)
    code = AT_LEAST_ONE.sub(".not_to_have_count(0)", code)
    return CONST_ASSERT.sub(lambda m: f"{m[1]}pass  # (was `assert True`: it checked nothing)", code)


def _with_said(code: str) -> str:
    """Add the `_said(page)` helper (what the website said, also in alert boxes) right after the file's imports. An
    own `_said` the AI wrote is replaced: it looked for the messages it EXPECTED ('text=Product added'), so it could
    only find what it guessed."""
    for node in ast.parse(code).body:
        if isinstance(node, ast.FunctionDef) and node.name == "_said":
            lines = code.split("\n")
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            code = "\n".join(lines[:first - 1] + lines[node.end_lineno:])
            break
    last = 0
    for node in ast.parse(code).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = node.end_lineno
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):  # (a module docstring)
            break
    lines = code.split("\n")
    return "\n".join(lines[:last] + [SAID_HELPER] + lines[last:])


def data_script(page: dict, cases: list[dict]) -> str:
    """Test data checks: every (input box, value) case is its own test. Values are typed, never submitted."""
    out = [
        f'"""Test data for {page["url"]}: each input box is tried with many different values.',
        "",
        "The value is typed into the box and checked there; the form is never submitted",
        '(so no accounts are created and no messages are sent)."""',
        "import pytest",
        "from playwright.sync_api import expect",
        "",
        f"URL = {page['url']!r}",
        *([] if page.get("auth") else ["pytestmark = pytest.mark.guest  # a public page: tested as a visitor"]),
        "",
        "",
        "def _settle(page):",
        "    try:",
        "        page.wait_for_load_state('networkidle', timeout=5000)",
        "    except Exception:",
        "        pass  # some sites never go fully idle",
        "",
        "",
        f"LINES_JS = {LINES_JS!r}",
        "# does the website itself refuse the value, visibly: the box marked invalid, or a new 'invalid ...' message",
        f"MARKED_JS = {MARKED_JS!r}",
        "",
        "",
        "def _inconclusive(reason):",
        "    \"\"\"The expected result could not be established: reported as INCONCLUSIVE with the reason.\"\"\"",
        "    print(f'[qa-inconclusive] {reason}')",
        "",
        "",
        "def _check(page, console_errors, selector, value, expectation):",
        "    page.goto(URL)",
        "    _settle(page)",
        "    lines_before = page.evaluate(LINES_JS)",
        "    popups = []",
        "",
        "    def on_dialog(dialog):",
        "        popups.append(dialog.message)",
        "        dialog.dismiss()",
        "",
        "    page.on('dialog', on_dialog)",
        "    try:",
        "        box = page.locator(selector).first",
        "        expect(box, 'the input box should be visible').to_be_visible(timeout=10000)",
        "        errors_before = len(console_errors)",
        "        typed = True",
        "        try:",
        "            box.fill(value)",
        "        except Exception as e:",
        "            if 'Cannot type' not in str(e) and 'alformed' not in str(e):",
        "                raise",
        "            typed = False  # the browser refused this value (e.g. letters in a number box)",
        "        box.dispatch_event('change')",
        "        box.blur()",
        "        page.wait_for_timeout(400)",
        "        kept = box.input_value() if typed else ''",
        "        valid = box.evaluate('el => el.checkValidity()')",
        "        message = box.evaluate('el => el.validationMessage')",
        "        shown = repr(value[:60]) + ('...' if len(value) > 60 else '')",
        "        assert not popups, f'A script ran after typing {shown}: popup {popups[0]!r} (XSS risk)'",
        "        new_errors = console_errors[errors_before:]",
        "        assert not new_errors, 'Typing this value caused JavaScript errors:\\n' + '\\n'.join(new_errors[:5])",
        "        if expectation == 'valid':",
        "            assert typed and valid, f'A valid value was rejected: {shown} ({message})'",
        "        elif expectation == 'invalid' and not value.strip() and typed and valid \\",
        "                and not box.evaluate('el => !!el.required'):",
        "            # required only by the website's own code (Angular, React - no `required` attribute): the browser",
        "            # does not check the box. The website marks it (ng-invalid / aria-invalid / a message), or refuses it",
        "            # only when the form is sent - which the tests never do",
        "            if not box.evaluate(MARKED_JS, lines_before):",
        "                _inconclusive(f'the box is required, but the browser does not check it and the website shows '",
        "                              f'nothing for {shown} until the form is sent - forms are never sent: not tested')",
        "        elif expectation == 'invalid':",
        "            assert (not typed) or (not valid) or kept != value, f'An invalid value was accepted: {shown}'",
        "        elif expectation == 'invalid?' and typed and valid and kept == value:  # (a text box: no browser check)",
        "            if not box.evaluate(MARKED_JS, lines_before):",
        "                _inconclusive(f'the box kept {shown} and shows no error - the browser does not check this box, '",
        "                              'and whether the website refuses it when the form is sent was not tested '",
        "                              '(forms are never sent)')",
        "        elif expectation.startswith('max:'):",
        "            limit = int(expectation[4:])",
        "            assert len(kept) <= limit, f'The box kept {len(kept)} characters, more than its limit of {limit}'",
        "    finally:",
        "        page.remove_listener('dialog', on_dialog)",
        "",
    ]
    for c in cases:
        title = c["title"].replace('"', "'")
        exp = "robust" if c["expect"] == "xss" else c["expect"]
        out += [
            "",
            f"def test_{_ident(c['id'])}(page, console_errors):",
            f'    """{title}"""',
            f"    _check(page, console_errors, {c['selector']!r}, {c['value']!r}, {exp!r})",
        ]
    return "\n".join(out) + "\n"


def link_test_id(url: str, external: bool) -> str:
    """The id of a link's own test in test_all_links.py - from the link alone, so the registry finds the result of a
    list's item links (an item list is judged by ITS links, never by a broken link elsewhere)."""
    import hashlib
    return (f"{'ext' if external else 'int'}_{_ident(re.sub(r'^https?://', '', url))[:40]}_"
            f"{hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:6]}")


def all_links_script(app_map: list[dict]) -> tuple[str, int]:
    """One test per UNIQUE link on the whole website (internal + external), and one per link to a part of a page
    (#projects): that part must exist. Returns (code, number of checks)."""
    from ..config import settings
    from .test_design import section_links
    links, seen = [], set()
    for p in app_map:
        for l in p.get("links", []):
            href = l["href"].split("#")[0]
            if href in seen or any(w in href.lower() for w in settings.unsafe_link_words) \
                    or (l.get("external") and not settings.check_external_links):
                continue
            seen.add(href)
            links.append({"id": link_test_id(href, bool(l.get("external"))),
                          "url": href, "text": (l.get("text") or "")[:60],
                          "found_on": p["url"], "external": bool(l.get("external"))})
    sections = [dict(s, id=f"sec_{n}_{_ident(s['section'])[:30]}")
                for n, s in enumerate(section_links([p for p in app_map if not p.get("error")]), start=1)]
    code = "\n".join([
        '"""Every link found on the whole website - each one is its own test.',
        'And every link to a part of a page (#projects): that part must exist on its page."""',
        "import pytest",
        "",
        f"LINKS = {pformat(links, width=110)}",
        f"SECTIONS = {pformat(sections, width=110)}",
        "# other websites that refuse automated requests (Facebook answers 400, LinkedIn 999 ...) are skipped, not failed",
        "BLOCKED_BY_SITE = {400, 401, 403, 405, 406, 429, 999}",
        "",
        "",
        "@pytest.mark.parametrize('sec', [pytest.param(s, id=s['id'], marks=[pytest.mark.guest] if s['guest'] else [])",
        "                                 for s in SECTIONS])",
        "def test_section_link(page, sec, qa_status):",
        '    """A link to a part of a page leads to a part that exists"""',
        "    qa_status(f'Checking section link {SECTIONS.index(sec) + 1} of {len(SECTIONS)}', sec['page'] + '#' + sec['section'],",
        "              f\"'{sec['text']}' - found on {sec['found_on']}\")",
        "    page.goto(sec['page'])",
        "    try:",
        "        page.wait_for_load_state('networkidle', timeout=5000)",
        "    except Exception:",
        "        pass  # some sites never go fully idle",
        "    found = page.evaluate(\"id => !!(document.getElementById(id) || document.getElementsByName(id).length)\", sec['section'])",
        "    assert found, (f\"The link '{sec['text']}' points to #{sec['section']} on {sec['page']}, but that page has no \"",
        "                   f\"such part - clicking it goes nowhere (found on {sec['found_on']})\")",
        "",
        "",
        "@pytest.mark.parametrize('link', LINKS, ids=[l['id'] for l in LINKS])",
        "def test_link(page, link, qa_status):",
        '    """Link opens without an error"""',
        "    # checked in the background (fast) - so the visible browser shows which link it is",
        "    qa_status(f'Checking link {LINKS.index(link) + 1} of {len(LINKS)}', link['url'],",
        "              f\"'{link['text']}' - found on {link['found_on']}\")",
        "    try:",
        "        r = page.request.get(link['url'], timeout=20000)",
        "    except Exception as e:",
        "        if link['external']:",
        "            pytest.skip(f'external site not reachable: {str(e)[:100]}')",
        "        raise AssertionError(f\"Link could not be opened: {link['url']} ({str(e)[:150]}) - found on {link['found_on']}\")",
        "    if link['external'] and r.status in BLOCKED_BY_SITE:",
        "        pytest.skip(f'the other website refuses automated checks (HTTP {r.status}) - not a defect of this site')",
        "    if link['external'] and r.status >= 500:",
        "        pytest.skip(f'the other website had a server error (HTTP {r.status}) - check the link again later')",
        "    if not link['external'] and r.status in (401, 403):",
        "        pytest.skip(f'needs other permissions (HTTP {r.status}): this account may not open it - not a broken link')",
        "    if r.status == 405:  # (an API address in a link: it answers its own method, POST / PUT - not a page to open)",
        "        pytest.skip('an API address: it does not accept a page visit (HTTP 405) - not a broken link')",
        "    assert r.status < 400, (f\"Broken link: HTTP {r.status}  {link['url']}  \"",
        "                            f\"(link text '{link['text']}', found on {link['found_on']})\")",
        "",
    ])
    return code, len(links) + len(sections)


def _origin(url: str) -> str:
    m = re.match(r"^(https?://[^/]+)", url or "")
    return m.group(1) if m else ""


# (used by the form tests: is a validation message shown, whatever the website calls its CSS classes?)
LINES_JS = "() => (document.body ? document.body.innerText : '').split('\\n').map(s => s.trim()).filter(Boolean)"
MARKED_JS = r"""(e, before) => {
  const around = `${e.className || ''} ${e.parentElement ? e.parentElement.className || '' : ''}`;
  if (e.getAttribute('aria-invalid') === 'true' || /\b(error|invalid|is-invalid|has-error|ng-invalid)\b/i.test(around)) return true;
  const lines = (document.body ? document.body.innerText : '').split('\n').map(s => s.trim()).filter(Boolean);
  return lines.some(l => !before.includes(l) && l.length < 160
                         && /invalid|not valid|enter a valid|valid (e-?mail|number|value|quantity)|incorrect|wrong format/i.test(l));
}"""
# A line counts as NEW when the page shows it more often than before: emptying a box may already show one 'Required'
# (OrangeHRM marks the box as soon as it is cleared) - the click then adds a second one under the next box. And an
# error-styled 'Required' under a box after the click is a refusal too, even if the first one was there before.
VALIDATION_JS = r"""(before) => {
  const shown = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                       return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const REFUSED = /required|must|mandatory|cannot be (empty|blank)|can't be (empty|blank)|please (enter|fill|provide|select|choose|complete)|invalid|is not valid|enter a valid|missing|too short|is empty/i;
  const tally = ls => ls.reduce((m, l) => m.set(l, (m.get(l) || 0) + 1), new Map());
  const lines = (document.body ? document.body.innerText : '').split('\n').map(s => s.trim()).filter(Boolean);
  const was = tally(before), now = tally(lines);
  const fresh = l => (now.get(l) || 0) > (was.get(l) || 0);
  const message = lines.filter(fresh).find(l => l.length < 160 && REFUSED.test(l)) || '';
  const errs = [...document.querySelectorAll('[class*=error i], [class*=invalid i], [role=alert]')]
    .filter(e => shown(e) && (e.innerText || '').trim()).map(e => (e.innerText || '').trim().split('\n')[0]);
  const marked = [...document.querySelectorAll('[aria-invalid=true]')].filter(shown).length +
    errs.filter(t => fresh(t) || (t.length < 80 && REFUSED.test(t))).length;
  return { message, marked };
}"""


def _check_counts(out_dir: Path) -> dict[str, int]:
    """How many single checks each small test case runs, read from the scripts themselves (new or reused)."""
    def read(name: str) -> str:
        f = out_dir / name
        return f.read_text(encoding="utf-8") if f.exists() else ""
    site = read("test_site.py")
    n_pages = site.count("'slug':")
    return {"site_pages_open": n_pages, "site_no_js_errors": n_pages,
            "site_images": len(re.findall(r"'images': [1-9]", site)),
            "site_links": read("test_all_links.py").count("'id': "),
            "site_input_values": sum(len(re.findall(r"^def test_data_", f.read_text(encoding="utf-8"), re.M))
                                     for f in out_dir.glob("test_*_data.py"))}


def _generate(state: QAState, pages: dict, cases: list[dict], save, rejected: list, notes: list) -> tuple[list, list]:
    """Write new scripts for the test cases. Returns (test cases - built-in ones replace the AI's if its code
    failed, notes)."""
    # 1) the large test cases written by the AI -> its own code; if that fails, built-in large cases instead
    ai = [c for c in cases if c.get("kind") == "flow" and c.get("ai")]
    if ai:
        code, lost, why = _llm_flows_in_batches(ai, pages)
        if code:
            save("test_flows_ai.py", code, "llm")
        if lost:
            print(f"  [script-gen] AI failed for {len(lost)} of its {len(ai)} journeys: {why[:200]} - those are left "
                  "out (the others and the built-in ones run)")
            rejected.append({"page": "site", "error": why})
            notes.append(f"The AI could not write working code for {len(lost)} of its {len(ai)} journeys; the other "
                         "test cases run.")
            # Unsupported proposals remain in the denominator with their rejection reason.
            gone = set(lost)
            cases = [dict(c, ai=False, files=[], tests=[], unsupported=True,
                          skip_reason="Unsupported AI proposal: " + why[:400]) if c.get("id") in gone else c
                     for c in cases]

    # 1b) the feature tests (filter, sort, next page, wishlist, long search): test_features.py
    feats = [c for c in cases if c.get("kind") == "feature"]
    if feats:
        code = features_script(feats)
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": err})
        else:
            save("test_features.py", code, "template")

    # 1c) what each control did while exploring - it must do it again: test_learned.py
    learned = [c for c in cases if c.get("kind") == "learned"]
    if learned:
        code = learned_script(learned)
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": err})
        else:
            save("test_learned.py", code, "template")

    # 1d) the data forms: valid values taken, wrong values refused (write guard: nothing sent unless staging), and on
    # staging create -> find -> edit -> delete + the cleanup at the end: test_forms.py, test_cleanup.py
    from ..forms import cleanup_script, forms_script
    header = ["import re", "import pytest", "from playwright.sync_api import expect", "", JOURNEY_HELPERS,
              RESULT_HELPERS, f"LINES_JS = {LINES_JS!r}", f"VALIDATION_JS = {VALIDATION_JS!r}",
              "APPROVE_JS = \"e => e.setAttribute('data-qa-approved', '1')\"  # (this test's one planned click)", ""]
    form_cases = [c for c in cases if c.get("kind") in ("form", "crud")]
    if form_cases:
        code = forms_script(form_cases, header)
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": f"test_forms.py: {err}"})
        else:
            save("test_forms.py", code, "template")
    items = [c for c in cases if c.get("kind") == "items"]
    if items:
        from ..items import items_script
        code = items_script(items, header)
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": f"test_items.py: {err}"})
        else:
            save("test_items.py", code, "template")
    mobile_c = [c for c in cases if c.get("kind") == "mobile"]
    if mobile_c:
        from ..mobile import mobile_script
        code = mobile_script(mobile_c, header)
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": f"test_mobile.py: {err}"})
        else:
            save("test_mobile.py", code, "template")
    role_c = [c for c in cases if c.get("kind") == "role"]
    if role_c:
        from ..roles import roles_script
        code = roles_script(role_c, header)
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": f"test_roles.py: {err}"})
        else:
            save("test_roles.py", code, "template")
    pairs = [c for c in cases if c.get("kind") == "pair"]
    if pairs:
        from ..form_rules import rules_script
        code = rules_script(pairs, header)
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": f"test_field_rules.py: {err}"})
        else:
            save("test_field_rules.py", code, "template")
    cleanup = [c for c in cases if c.get("kind") == "cleanup"]
    if cleanup:
        code = cleanup_script(cleanup[0], header)
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": f"test_cleanup.py: {err}"})
        else:
            save("test_cleanup.py", code, "template")

    # 2) built-in real user journeys (log in, shop, fill forms, click through the menu): test_journeys.py
    journeys = [c for c in cases if c.get("kind") == "journey"]
    if journeys:
        code = journeys_script(journeys)
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": err})
        else:
            save("test_journeys.py", code, "template")

    # 3) the focused checks: the steps of each page (steps_<page>.py) + test_checks.py - one test per check
    checks = [c for c in cases if c.get("kind") == "check"]
    modules = {}
    for slug in dict.fromkeys(c["parts"][0]["page"] for c in checks):
        code = steps_module(pages[slug], [c["parts"][0]["step"] for c in checks if c["parts"][0]["page"] == slug])
        err = validate_script(code, need_tests=False)
        if err:
            rejected.append({"page": slug, "error": err})
            continue
        modules[slug] = code
        save(f"steps_{_ident(slug)}.py", code, "template")
    if checks:
        code, missing = checks_script(checks, modules)
        if missing:
            notes.append(f"{len(missing)} check(s) have no automatic code yet: " + "; ".join(missing[:5]))
        err = validate_script(code)
        if err:
            rejected.append({"page": "site", "error": err})
        else:
            save("test_checks.py", code, "template")

    # 4) the 5 small checks: every page / every link / every input box
    if pages:
        save("test_site.py", site_script(list(pages.values())), "template")
    code, n_links = all_links_script(state["app_map"])
    if n_links:
        save("test_all_links.py", code, "template")
    data = next((c.get("checks") or [] for c in cases if c.get("id") == "site_input_values"), [])
    for slug in dict.fromkeys(c["page"] for c in data):
        if slug in pages:
            code = data_script(pages[slug], [c for c in data if c["page"] == slug])
            if not validate_script(code):
                save(f"test_{_ident(slug)}_data.py", code, "template")
    return cases, notes


def script_generator_agent(state: QAState) -> QAState:
    """Writes the code of the test cases - one test function per test case, each with its own result:
      test_journeys.py                    real user journeys (log in, search -> product -> cart, forms, the menu)
      test_checks.py + steps_<page>.py    one focused check per feature / control of each page
      test_features.py, test_learned.py   feature rules (sort, filter, pages, quantity ...), learned behaviour
      test_flows_ai.py                    the AI's own journeys (with an AI)
      test_site.py, test_<page>_data.py, test_all_links.py   the site-wide checks (pages, input values, links)
    They run in that order: the journeys first, the link checks last (see conftest.py).
    """
    if state.get("target_type") == "mobile":
        from ..android_design import generate_scripts
        return generate_scripts(state)
    if state.get("contract_only"):
        note = "Contract-only run: approved flows execute through the maintained Playwright contract runtime."
        print("  [script-gen] " + note)
        return {"scripts": [], "script_sources": {"qa_contracts.json": "contract"},
                "script_errors": [], "test_cases": state.get("test_cases", []),
                "log": state.get("log", []) + [note]}
    run_dir = Path(state["run_dir"])
    out_dir = run_dir / "generated_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in list(out_dir.glob("test_*.py")) + list(out_dir.glob("steps_*.py")):
        old.unlink()  # (a healing re-run never comes back here, so this only clears an earlier attempt)
    shutil.copy(TEMPLATES / "conftest.py", out_dir / "conftest.py")  # fixtures + the runtime sandbox
    shutil.copy(TEMPLATES / "pytest.ini", out_dir / "pytest.ini")

    pages = {p["slug"]: p for p in state["app_map"] if not p.get("error") and (p.get("status") or 0) < 400}
    cases = list(state["test_cases"])
    scripts, sources, rejected, notes = [], {}, [], []

    def save(name: str, code: str, source: str):
        (out_dir / name).write_text(f"# generated by: {source}\n" + code, encoding="utf-8")
        if name.startswith("test_"):
            scripts.append(str(out_dir / name))
        sources[name] = source
        print(f"  [script-gen] {source:8s} {name}")

    from ..config import settings
    from .change_detection import saved_tests
    saved = saved_tests(state["site_key"]) if settings.reuse_tests else None
    if saved:  # regression run: the scripts of the last run, run again unchanged (checked again first)
        old, new = saved["meta"].get("origin", ""), _origin(state["url"])
        for f in saved["files"]:
            code = re.sub(r"^# generated by: .*\n", "", f.read_text(encoding="utf-8"), count=1)
            if old and new and old != new:
                code = code.replace(old, new)  # the same site on another address (e.g. a new port)
            err = validate_script(code, need_tests=f.name.startswith("test_"))
            if err:
                rejected.append({"page": f.name, "error": err})
                continue
            save(f.name, code, "reused")
        notes.append(f"Regression run: the {len(scripts)} test file(s) of the run of {saved['meta'].get('date', '?')} "
                     "were run again unchanged (no new tests were written).")
    else:
        cases, notes = _generate(state, pages, cases, save, rejected, notes)

    # how many single checks each test case runs (the live list shows a case as running until all are done) -
    # its own field: "expected" is the case's expected RESULT (Excel, report, bug reports) and must stay so
    counts = _check_counts(out_dir)
    for c in cases:
        c["check_count"] = counts.get(c["id"], 1)
    from .test_design import finalize_cases
    cases = finalize_cases(cases, state)  # structured fields + stable IDs (also for built-in replacements)

    # 5) coverage: every control found, and whether a generated test really uses it (chat, Excel, report)
    all_code = "\n".join(f.read_text(encoding="utf-8") for f in out_dir.glob("*.py") if f.name != "conftest.py")
    from .test_design import COVERAGE_SCRIPTED_NOTE, coverage
    cov = [coverage(p, all_code) for p in pages.values()]
    tested, total = sum(x["tested"] for x in cov), sum(x["total"] for x in cov)
    login = state.get("login") or {}
    honesty = [COVERAGE_SCRIPTED_NOTE]
    Path(run_dir, "coverage.json").write_text(json.dumps(
        {"tested": tested, "total": total, "pages": cov,
         # (not logged in -> say why; logged in with an account the tester created -> say which one)
         "notes": honesty + ([login["note"]] if login.get("found") and (not login.get("logged_in") or
                                                              (login.get("account") or {}).get("how") != "given")
                   else []) + notes},
        indent=2), encoding="utf-8")
    print(f"  [script-gen] coverage: {tested} of {total} controls are used by the tests")

    Path(run_dir, "test_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    write_workbook(run_dir, cases)  # Excel now shows the Automation Status

    counts = {}
    for v in sources.values():
        counts[v] = counts.get(v, 0) + 1
    log = state.get("log", []) + [f"Script generation: {len(scripts)} test files {counts}; {len(rejected)} rejected."
                                  + (" " + " ".join(notes) if notes else "")]
    return {"scripts": scripts, "script_sources": sources, "script_errors": rejected, "log": log, "test_cases": cases}
