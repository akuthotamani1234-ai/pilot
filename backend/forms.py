"""Forms that create, change or send data - checked the way a tester checks them (Steps 4 + 5).

Which forms: the DATA forms found while exploring - not a search / filter form, not the login form, never a form that
pays or deletes. The same control on many pages (the footer's newsletter form) is one form, tested once.

  valid        every box gets a valid value (backend/testdata.py; names / texts carry the run's tag qa-<run>-<n>)
               staging:            the form is SENT -> accepted (a success message, another page, no error)
               test / production:  the write_guard stops what the page sends -> accepted = it TRIED to send it
                                   ("would send" - nothing reached the website)
  wrong values one test per box: each wrong value (the others valid) -> refused: an error is shown / the box is marked
               invalid, and nothing is sent. Without sending (guard): a wrong value the page lets through while it
               refused another wrong value of the same box is a bug ('a@' sent, 'qa.tester' refused); a box the page
               does not check at all is INCONCLUSIVE (its check happens on the server - unknown without sending).
               'either' values are only recorded.
  round trip   staging: create -> find it in the list -> edit one field -> the change shows -> delete (only with
               ALLOW_ACTIONS=delete) -> gone. Everything created is written to created.jsonl; test_cleanup.py removes
               what is left (if deleting is allowed), the rest is reported "left for manual cleanup".
"""
import re
from pprint import pformat
from urllib.parse import urlparse

from .actions import DELETE, PAY, action_risk, writes_allowed
from .form_targets import FORM_TARGET_HELPER
from .navigation import OPEN_PATH_HELPER, opener_path
from .testdata import field_kind, valid_value, values

SEARCHY = re.compile(r"\b(q|query|search|keywords?|s)\b", re.I)
QTY = re.compile(r"\bqty\b|quantit", re.I)
CART_FORM = re.compile(r"\b(cart|basket|trolley)\b", re.I)
CREATE_PATH = re.compile(r"/(new|create|add|register)(/|$)|[?&](action|mode)=(new|create|add)\b", re.I)
EDIT_TEXT = re.compile(r"^\s*(edit|modify|change)\b", re.I)
MAX_FORMS, MAX_WRONG_BOXES = 10, 6


def _inputs_by_selector(p: dict) -> dict:
    return {i.get("selector"): i for i in p.get("inputs", []) if i.get("selector")}


def is_login_form(f: dict) -> bool:
    pw = [x for x in f.get("fields", []) if (x.get("type") or "") == "password"]
    sign_up = re.search(r"regist|sign ?up|create|join", (f.get("submit") or {}).get("text") or "", re.I)
    return len(pw) == 1 and len([x for x in f["fields"] if x.get("type") not in ("checkbox", "hidden")]) <= 3 \
        and not sign_up


def data_forms(pages: list[dict]) -> list[dict]:
    """Every data form of the site, once: (page, form, its boxes with what they are for)."""
    out, seen = [], set()
    for p in pages:
        known = _inputs_by_selector(p)
        for f in p.get("forms", []):
            submit = f.get("submit") or {}
            said = submit.get("text") or ""
            if not submit.get("selector") or PAY.search(said) or DELETE.search(said):
                continue  # (never a form that pays or deletes - not even with wrong values)
            fields = [dict(known.get(x["selector"], {}), **x) for x in f.get("fields", []) if x.get("selector")]
            if not fields or is_login_form(f):
                continue
            searchy = any((x.get("type") or "") == "search" or SEARCHY.search(
                f"{x.get('name')} {x.get('id')} {x.get('label')} {x.get('placeholder')}") for x in fields)
            required = any(x.get("required") for x in fields)
            if (searchy and not required) or (f.get("method", "get") == "get" and not required):
                continue  # a search / filter / sort form (it only shows other results): its own feature tests
            if p.get("page_type") == "cart" or CART_FORM.search(said) or any(
                    QTY.search(f"{x.get('name')} {x.get('id')} {x.get('label')}") for x in fields):
                continue  # a cart's 'Update' / an 'Add to cart' form: the cart tests (an empty cart has no such form)
            key = (tuple(sorted(x["selector"] for x in fields)), submit.get("selector"))
            if key in seen:
                continue
            seen.add(key)
            boxes = []
            for x in fields:
                kind = field_kind(x)
                boxes.append({"selector": x["selector"], "name": _name(x), "kind": kind,
                              "label": x.get("label") or "", "local_selector": x.get("local_selector"),
                              "type": (x.get("type") or "").lower(), "tag": x.get("tag") or "",
                              "required": bool(x.get("required")),
                              "valid": valid_value(x, "{tag}") if kind else "",
                              "tagged": kind in ("names", "text", "email")})
            out.append({"page": p, "form": f, "boxes": boxes, "name": _form_name(p, f),
                        "openers": opener_path(p, f["selector"], f.get("revealed_by"))})
            if len(out) >= MAX_FORMS:
                return out
    return out


def _name(x: dict) -> str:
    return (x.get("label") or x.get("placeholder") or x.get("name") or x.get("id") or "box").split("\n")[0].strip()[:40]


def _form_name(p: dict, f: dict) -> str:
    said = ((f.get("submit") or {}).get("text") or "").strip()
    return f"{said or 'the form'} ({urlparse(p['url']).path or '/'})"[:70]


def _spec(d: dict) -> dict:
    f = d["form"]
    return {"url": d["page"]["url"], "form": f["selector"], "submit": f["submit"]["selector"],
            "submit_text": f["submit"].get("text") or "", "boxes": d["boxes"], "openers": d.get("openers") or []}


def _guarded() -> bool:
    return not writes_allowed()


def form_cases(pages: list[dict]) -> list[dict]:
    """The test cases of every data form: valid values accepted, wrong values refused (one test per box)."""
    out = []
    guard = _guarded()
    how = "the write guard stops what the page sends (nothing reaches the website)" if guard else "the form is sent"
    for n, d in enumerate(data_forms(pages), start=1):
        spec, page = _spec(d), d["page"]
        base = {"kind": "form", "page": page["slug"], "url": page["url"], "pages": [page["slug"]],
                "guest": not page.get("auth"), "files": ["test_forms.py"],
                "verification_level": "input_only" if guard else "submitted",
                "business_verified": False}
        # sending valid values to the edit form of an EXISTING record would overwrite it: on staging the round trip
        # edits its own record instead (without sending, the guard keeps it harmless)
        existing = re.search(r"/(\d+|[0-9a-f-]{8,})/(edit|update)\b|/edit(/|$)", urlparse(page["url"]).path, re.I)
        cid = f"form_valid_{n}"
        if existing and not guard:
            cid = None
        out += [] if cid is None else [dict(base, id=cid, tests=[f"test_{cid}"], type="positive", priority="high",
                        title=f"Form '{d['name']}': valid values are accepted",
                        steps=[f"Open {page['url']}", "Fill every box with a valid value"
                               + (" (names / texts carry the run's tag)" if not guard else ""),
                               f"Click '{spec['submit_text'] or 'Submit'}' - {how}"],
                        expected=("The page sends the form (a write request would go out) and shows no error"
                                  if guard else "The form is accepted: a success message or the next page, no error"),
                        test_data=", ".join(f"{b['name']}={b['valid']}" for b in d["boxes"] if b["valid"])[:200],
                        spec=dict(spec, mode="guard" if guard else "send"))]
        for k, b in enumerate([b for b in d["boxes"] if b["kind"]][:MAX_WRONG_BOXES], start=1):
            box = next(x for x in d["form"]["fields"] if x["selector"] == b["selector"])
            vals = values(dict(_inputs_by_selector(page).get(b["selector"], {}), **box))
            wrong = [v for v in vals if v["expect"] == "reject"][:4]
            either = [v for v in vals if v["expect"] == "either"][:2]
            if not wrong:
                continue
            cid = f"form_wrong_{n}_{k}"
            shown = ", ".join(repr(v["value"]) for v in wrong)
            out.append(dict(base, id=cid, tests=[f"test_{cid}"], type="negative", priority="high",
                            title=f"Form '{d['name']}': wrong values in '{b['name']}' are refused",
                            steps=[f"Open {page['url']}", "Fill every other box with a valid value",
                                   f"Type each wrong value into '{b['name']}': {shown}",
                                   f"Click '{spec['submit_text'] or 'Submit'}' each time"],
                            expected=f"Each wrong value is refused with a visible error ('{b['name']}' marked "
                                     "invalid) and nothing is sent",
                            test_data=shown[:200],
                            spec=dict(spec, mode="guard" if guard else "send", box=b["selector"], box_name=b["name"],
                                      wrong=wrong, either=either)))
    return out


# ---------------------------------------------------------------- create -> find -> edit -> delete (staging)

def _parent(path: str) -> str:
    return re.sub(r"/[^/]*$", "", path.rstrip("/")) or "/"


def crud_targets(pages: list[dict]) -> list[dict]:
    """Forms that CREATE something that then appears in a list: the form's page is /x/new (create / add / register)
    and the page above it (/x) lists items - a table or repeated cards. Edit / delete come from that list's rows."""
    by_path = {urlparse(p["url"]).path.rstrip("/") or "/": p for p in pages}
    out = []
    for d in data_forms(pages):
        path = urlparse(d["page"]["url"]).path
        if not CREATE_PATH.search(path) and not re.search(r"\b(create|add|new)\b", d["form"]["submit"].get("text") or "",
                                                         re.I):
            continue
        lst = by_path.get(_parent(path))
        if not lst or lst is d["page"]:
            continue
        name_box = next((b for b in d["boxes"] if b["kind"] in ("names", "text")), None)
        if not name_box:
            continue
        edit = any(EDIT_TEXT.search(l.get("text") or "") for l in lst.get("links", [])) or \
            any(EDIT_TEXT.search(b.get("text") or "") for b in lst.get("buttons", []))
        dele = next((b for b in lst.get("buttons", []) if DELETE.search(b.get("text") or "")), None)
        search = next((i["selector"] for i in lst.get("inputs", []) if i.get("selector") and
                       ((i.get("type") or "") == "search" or re.search(r"search|filter|find", f"{i.get('label')} "
                                                                       f"{i.get('placeholder')} {i.get('id')}", re.I))),
                      None)
        out.append({"form": d, "list": lst, "name_box": name_box["selector"], "edit": edit,
                    "delete_text": (dele or {}).get("text") or "",
                    "delete_allowed": bool(dele) and action_risk(dele.get("text"), dele.get("selector")) == "write",
                    "search": search})
    return out


def crud_cases(pages: list[dict]) -> list[dict]:
    if not writes_allowed():
        return []
    out = []
    for n, t in enumerate(crud_targets(pages), start=1):
        d, lst = t["form"], t["list"]
        steps = [f"Open {d['page']['url']} and create a record with valid, tagged values (qa-<run>-<n>)",
                 f"Open {lst['url']}: the new record is listed"]
        if t["edit"]:
            steps += ["Edit it: change its name", "The list shows the new name"]
        if t["delete_allowed"]:
            steps += [f"Click '{t['delete_text']}' on its row", "It is no longer listed"]
        cid = f"crud_{n}"
        out.append({"id": cid, "kind": "crud", "type": "positive", "priority": "high",
                    "title": f"Create -> find -> {'edit -> ' if t['edit'] else ''}"
                             f"{'delete' if t['delete_allowed'] else 'keep'} a record ({urlparse(lst['url']).path})",
                    "steps": steps,
                    "expected": "Each step shows its result: the record appears, the change is saved"
                                + (", and it is gone after deleting" if t["delete_allowed"] else ""),
                    "page": d["page"]["slug"], "url": d["page"]["url"], "pages": [d["page"]["slug"], lst["slug"]],
                    "guest": not d["page"].get("auth"), "test_data": "qa-<run>-<n> tagged values",
                    "files": ["test_forms.py"], "tests": [f"test_{cid}"],
                    "spec": dict(_spec(d), list_url=lst["url"], name_box=t["name_box"], edit=t["edit"],
                                 delete=t["delete_allowed"], delete_text=t["delete_text"], search=t["search"])})
    return out


def cleanup_case(cases: list[dict]) -> list[dict]:
    """Staging: one last test removes what the run created and could not remove itself (if deleting is allowed)."""
    crud = [c for c in cases if c.get("kind") == "crud"]
    if not crud:
        return []
    return [{"id": "cleanup", "kind": "cleanup", "type": "positive", "priority": "low",
             "title": "Clean up the test data this run created",
             "steps": ["Find every record tagged with this run's tag (created.jsonl)",
                       "Delete it through the website's own Delete button (only if deleting is allowed)"],
             "expected": "Nothing tagged with this run is left (or it is listed for manual cleanup)",
             "page": crud[0]["page"], "url": crud[0]["spec"]["list_url"], "pages": crud[0]["pages"], "guest": False,
             "test_data": "", "files": ["test_cleanup.py"], "tests": ["test_cleanup"],
             "spec": {"lists": [{"list_url": c["spec"]["list_url"], "form_url": c["spec"]["url"],
                                 "search": c["spec"]["search"], "delete": c["spec"]["delete"],
                                 "delete_text": c["spec"]["delete_text"]} for c in crud]}}]


# ---------------------------------------------------------------- the code (test_forms.py, test_cleanup.py)

FORM_HELPERS = OPEN_PATH_HELPER + '\n' + FORM_TARGET_HELPER + r'''
def _visible(loc):
    try:
        return loc.count() > 0 and loc.first.is_visible()
    except Exception:
        return False


def _fill_form(page, F, tag, bad=None):
    """A valid value in every box (names / texts / e-mails carry the run's tag) - except `bad`: (selector, value)."""
    groups = set()
    for b in F['boxes']:
        scope = form_scope(page, F.get('form'))
        el = unique_control(scope, b)
        if not _visible(el):
            pytest.skip(f"Recorded field '{b['name']}' is not visible after reopening the form; filling was not verified")
        if not el.is_enabled():
            if b.get('required'):
                pytest.skip(f"Required field '{b['name']}' is disabled; whole-form input was not verified")
            if bad and b['selector'] == bad[0]:
                pytest.skip(f"'{b['name']}' is disabled on this page - nothing can be typed into it")
            continue
        if bad and b['selector'] == bad[0]:
            el.fill(bad[1])
            continue
        if b['type'] == 'checkbox':
            if b['required']:
                check_user_control(scope, b, True)
            continue
        if b['type'] == 'radio':
            name = el.get_attribute('name') or b['selector']
            if name not in groups:
                groups.add(name)
                # (a choice that is already made - 'Round trip' - is kept, like a person would)
                if not page.locator(f'input[type=radio][name="{name}"]:checked').count():
                    check_user_control(scope, b, True)
            continue
        if b['tag'] == 'select' or b['type'].startswith('select'):
            options = el.evaluate("e => [...e.options].filter(o => !o.disabled && o.value).map(o => o.value)")
            if options and not el.input_value():
                el.select_option(options[0])
            continue
        if b['type'] == 'file' or not b['kind']:
            if b.get('required'):
                pytest.skip(f"Required field '{b['name']}' needs a supported control value")
            continue
        value = b['valid']
        if b['kind'] == 'email':
            value = f"{tag}@example.com"
        elif b['tagged']:
            value = value.replace('{tag}', tag)
        el.fill(value)
        expect(el, "The input must retain its intended test value").to_have_value(value)


def _send(page, F):
    """Click the form's own button (this one planned click is approved; on test / production the write guard stops
    what it sends)."""
    btn = page.locator(F['submit'])
    expect(btn, 'The form submit button must be unique').to_have_count(1)
    expect(btn, 'the form\'s button should be visible').to_be_visible()
    btn.evaluate(APPROVE_JS)
    btn.click()
    page.wait_for_timeout(1200)
    _settle(page)


def _box_invalid(page, sel):
    try:
        return bool(page.locator(sel).first.evaluate(
            "e => (e.matches && e.matches(':invalid')) || e.getAttribute('aria-invalid') === 'true'"))
    except Exception:
        return False


def _outcome(page, F, before, start, tried=None, box=None):
    """What the form did: 'sent' (the page tried to send it - guard mode), 'refused' (an error / an invalid box),
    'accepted' (sent mode: another page or a success message, no error) or 'silent' (nothing visible happened)."""
    if tried is not None and tried:
        return 'sent', f"{tried[-1]['method']} {tried[-1]['path']}"
    found = page.evaluate(VALIDATION_JS, before)
    msgs = [m for m in _messages(page) if m not in before]
    bad = [m for m in msgs if _tone(m) == 'error']
    if found['message'] or found['marked'] or bad or (box and _box_invalid(page, box)):
        return 'refused', found['message'] or (bad[0] if bad else 'the box is marked invalid')
    if tried is not None:
        return 'silent', ''
    left = page.url.split('#')[0].rstrip('/') != start.split('#')[0].rstrip('/')
    ok = [m for m in msgs if _tone(m) == 'ok']
    if left or ok:
        return 'accepted', ok[0] if ok else f'went on to {page.url}'
    return 'silent', ''


def _try_form(page, F, tag, write_guard=None, bad=None):
    page.goto(F['url'])
    _settle(page)
    if F.get('openers'):
        open_path(page, F['openers'], F['boxes'][0]['selector'])
    _fill_form(page, F, tag, bad)
    before, start = page.evaluate(LINES_JS), page.url
    n = len(write_guard) if write_guard is not None else 0
    _send(page, F)
    tried = write_guard[n:] if write_guard is not None else None
    return _outcome(page, F, before, start, tried, bad[0] if bad else None)


def _check_valid(page, F, tag, write_guard=None, track=None):
    what, how = _try_form(page, F, tag, write_guard)
    if track and what != 'refused':
        track('form', tag, F['url'])  # (staging: it may have created something - the cleanup looks for the tag)
    if what == 'refused':  # (the website's own rule may differ from the value the test thought valid: review it)
        _inconclusive(f"the form refused the values the test took for valid: {how!r} - check the value or the rule")
        return
    if what == 'silent':
        _inconclusive("the form neither sent the values nor showed a message (it may need something the test can't "
                      "give: a CAPTCHA, a choice, an upload)")
        return
    assert what in ('sent', 'accepted'), what
    _step_ok(f"valid values: would send ({how}) - stopped by the write guard, nothing reached the website"
             if what == 'sent' else f"valid values accepted: {how}")


def _check_wrong(page, F, tag, write_guard=None, track=None):
    seen = []
    for v in F['wrong']:
        what, how = _try_form(page, F, tag, write_guard, (F['box'], v['value']))
        seen.append((v['value'], what, how))
        if track and what == 'accepted':
            track('form', tag, F['url'])
    for v in F.get('either', []):
        what, how = _try_form(page, F, tag, write_guard, (F['box'], v['value']))
        _step_ok(f"'{F['box_name']}' = {v['value']!r} ({v['why']}): {what} - recorded, no rule either way")
    for value, what, how in seen:
        _step_ok(f"'{F['box_name']}' = {value!r}: {what}" + (f" ({how})" if how else ""))
    refused = [s for s in seen if s[1] == 'refused']
    passed = [s for s in seen if s[1] in ('sent', 'accepted')]
    if F['mode'] == 'guard':
        # Without sending: the evidence of a bug is a TYPED wrong value sent while another typed wrong value of the
        # same box was refused - the page does check what is typed, and lets this one through ('a@' sent, 'qa.tester'
        # refused). An empty box refused only says "required". Typed values sent with none refused: the box's check
        # happens on the server - unknown without sending (staging tests it).
        typed_refused = [s for s in refused if s[0] != '']
        typed_sent = [s for s in passed if s[0] != '']
        assert not (typed_sent and typed_refused), (
            f"'{F['box_name']}' = {typed_sent[0][0]!r} was sent - a wrong value the form should refuse "
            f"({typed_sent[0][2]}); {typed_refused[0][0]!r} was refused, so the form does check this box")
        if typed_sent:
            _inconclusive(f"the page does not check '{F['box_name']}' before sending (it would send "
                          f"{typed_sent[0][0]!r}): the website's own check happens when the form is sent")
            return
    else:  # staging: the website itself took a wrong value
        assert not passed, (f"'{F['box_name']}' = {passed[0][0]!r} was accepted - a wrong value the form should "
                            f"refuse ({passed[0][2]})")
    if not refused:
        _inconclusive(f"'{F['box_name']}': the form neither refused the wrong values nor sent them - no evidence "
                      "either way (it may need something the test can't give)")
        return
    assert refused, "no wrong value was refused"


def _find_row(page, C, text):
    """The row / card of the list that shows `text` (using the list's search box when it has one)."""
    page.goto(C['list_url'])
    _settle(page)
    if C.get('search') and _visible(page.locator(C['search'])):
        page.locator(C['search']).first.fill(text)
        page.wait_for_timeout(800)
    for _ in range(6):
        rows = page.locator('tr, li, [class*=card i], [class*=item i], [class*=row i]').filter(has_text=text)
        if rows.count():
            return rows.first
        nxt = page.locator('button:has-text("Next"), a:has-text("Next"), [rel=next]').first
        if not _visible(nxt) or not nxt.is_enabled():
            return None
        nxt.click()
        page.wait_for_timeout(600)
    return None


def _delete_row(page, row, text_of_button):
    btn = row.locator(f'button:has-text("{text_of_button}"), a:has-text("{text_of_button}"), '
                      f'input[value="{text_of_button}"]').first
    btn.evaluate(APPROVE_JS)
    page.once('dialog', lambda d: d.accept())  # (staging + ALLOW_ACTIONS=delete: the confirm box is answered OK)
    btn.click()
    page.wait_for_timeout(1000)
    _settle(page)


def _check_crud(page, C, tag, track_created):
    page.goto(C['url'])
    _settle(page)
    _fill_form(page, C, tag)
    before, start = page.evaluate(LINES_JS), page.url
    _send(page, C)
    what, how = _outcome(page, C, before, start)
    assert what != 'refused', f"Creating the record was refused: {how}"
    track_created('record', tag, C['list_url'])
    _step_ok(f"created a record tagged {tag}")
    row = _find_row(page, C, tag)
    assert row is not None, f"The new record ({tag}) is not listed on {C['list_url']}"
    _step_ok(f"it is listed on {C['list_url']}")
    if C['edit']:
        row.locator('a, button').filter(has_text=re.compile(r'^\s*(edit|modify|change)', re.I)).first.click()
        _settle(page)
        box = page.locator(C['name_box']).first
        expect(box, 'the edit form should show the name box').to_be_visible()
        changed = f"QA {tag} edited"
        box.fill(changed)
        before, start = page.evaluate(LINES_JS), page.url
        _send(page, C)
        what, how = _outcome(page, C, before, start)
        assert what != 'refused', f"Saving the change was refused: {how}"
        assert _find_row(page, C, f"{tag} edited") is not None, (
            f"The edited name '{changed}' was not saved: the list still shows the old one")
        _step_ok("the change is saved and shown in the list")
    if C['delete']:
        row = _find_row(page, C, tag)
        assert row is not None, f"The record ({tag}) can't be found again to delete it"
        _delete_row(page, row, C['delete_text'])
        assert _find_row(page, C, tag) is None, f"The record ({tag}) is still listed after '{C['delete_text']}'"
        track_created('record', tag, C['list_url'], 'deleted')
        _step_ok("deleted - it is gone from the list")
'''


def forms_script(cases: list[dict], header: list[str]) -> str:
    """test_forms.py - `header`: the imports + shared helpers of the generated files (script_generator)."""
    out = ['"""Forms checked like a tester: valid values are taken, wrong values are refused (nothing is sent when the',
           'run must not change data: the write guard stops it), and on staging: create -> find -> edit -> delete."""',
           *header, FORM_HELPERS, ""]
    for c in cases:
        spec, kind = c["spec"], c["kind"]
        guard = spec.get("mode") == "guard"
        args = ["page"] + (["write_guard"] if guard and kind == "form" else []) + ["qa_tag"] \
            + (["track_created"] if kind == "crud" or not guard else [])
        extra = ", write_guard" if guard else ", track=track_created"
        out += (["@pytest.mark.guest  # a public page: tested as a visitor"] if c.get("guest") else []) + [
            f"def test_{c['id']}({', '.join(args)}):",
            f'    """{c["title"].replace(chr(34), chr(39)).replace(chr(92), "/")}"""',
            f"    F = {pformat(spec, width=100, sort_dicts=False)}".replace("\n", "\n        ")]
        if kind == "crud":
            out += ["    _check_crud(page, F, qa_tag(), track_created)"]
        elif c["id"].startswith("form_valid"):
            out += [f"    _check_valid(page, F, qa_tag(){extra})"]
        else:
            out += [f"    _check_wrong(page, F, qa_tag(){extra})"]
        out += ["", ""]
    return "\n".join(out).rstrip() + "\n"


CLEANUP_HELPERS = r'''
def test_cleanup(page, created_so_far, track_created):
    """Clean up the test data this run created"""
    latest = {}
    for r in created_so_far:
        latest[r['tag']] = r
    left = [r for r in latest.values() if r['status'] == 'created']
    if not left:
        pytest.skip('nothing to clean up: every record this run created was deleted by its own test' if latest
                    else 'this run created nothing')
    still = []
    for r in left:
        spec = next((s for s in C['lists'] if r['where'] in (s['list_url'], s['form_url'])), None)
        if not spec or not spec['delete']:
            track_created('record', r['tag'], r['where'], 'left')
            still.append(r['tag'])
            continue
        row = _find_row(page, spec, r['tag'])
        if row is None:  # (gone already)
            track_created('record', r['tag'], r['where'], 'deleted')
            continue
        _delete_row(page, row, spec['delete_text'])
        if _find_row(page, spec, r['tag']) is None:
            track_created('record', r['tag'], r['where'], 'deleted')
        else:
            track_created('record', r['tag'], r['where'], 'left')
            still.append(r['tag'])
    if still:
        _inconclusive(f"{len(still)} record(s) left for manual cleanup (deleting is not allowed or did not work): "
                      + ', '.join(still[:10]))
        return
    _step_ok(f"removed {len(left)} record(s) this run created")
    assert not still, f"left for manual cleanup: {still}"
'''


def cleanup_script(case: dict, header: list[str]) -> str:
    return "\n".join(['"""Runs LAST on staging: removes what the run created (tagged qa-<run>-<n>), or lists it for manual',
                      'cleanup."""', *header, FORM_HELPERS, "",
                      f"C = {pformat(case['spec'], width=100, sort_dicts=False)}", "", CLEANUP_HELPERS]).rstrip() + "\n"
