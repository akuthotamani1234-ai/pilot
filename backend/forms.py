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

Target identity: fill/assert only inside the form / dialog / labeled section; prefer label, role/name and stable id;
never use Playwright .first to hide ambiguous matches - unresolved ambiguity is automation/inconclusive (fail closed).
Sidebar/global search and unrelated table row checkboxes are not form fill targets. A missing or invisible required
field means the whole-form check cannot pass; optional/conditional fields need an explicit skip reason.
"""
import inspect
import re
from pprint import pformat
from urllib.parse import urlparse

from .actions import DELETE, action_risk, writes_allowed
from .navigation import OPEN_PATH_HELPER, opener_path
from .testdata import field_kind, valid_value, values

SEARCHY = re.compile(r"\b(q|query|search|keywords?|s)\b", re.I)
QTY = re.compile(r"\bqty\b|quantit", re.I)
CART_FORM = re.compile(r"\b(cart|basket|trolley)\b", re.I)
CREATE_PATH = re.compile(r"/(new|create|add|register)(/|$)|[?&](action|mode)=(new|create|add)\b", re.I)
EDIT_TEXT = re.compile(r"^\s*(edit|modify|change)\b", re.I)
CHROME_REGION = re.compile(r"^(sidebar|nav|header|banner|complementary|aside|navigation)$", re.I)
MAX_FORMS, MAX_WRONG_BOXES = 10, 6


class FormTargetProblem(Exception):
    """Ambiguous or missing form target - never silently pick one match with .first."""

    kind = "missing_optional"


def form_target_problem(kind: str, message: str) -> FormTargetProblem:
    """Build a FormTargetProblem without a custom __init__ (generated scripts ban .__init__)."""
    err = FormTargetProblem(message)
    err.kind = kind  # ambiguous | missing_required | missing_optional
    return err


def _inputs_by_selector(p: dict) -> dict:
    return {i.get("selector"): i for i in p.get("inputs", []) if i.get("selector")}


def _field_hint(x: dict) -> str:
    return f"{x.get('name')} {x.get('id')} {x.get('label')} {x.get('placeholder')} {x.get('accname')}"


def is_chrome_search_field(x: dict) -> bool:
    """Sidebar / header / global search boxes are never filled as part of a data form."""
    hint = _field_hint(x)
    searchy = (x.get("type") or "").lower() == "search" or SEARCHY.search(hint) or field_kind(x) == "search"
    if not searchy:
        return False
    region = str(x.get("region") or "")
    return bool(x.get("chrome") or CHROME_REGION.match(region)
                or re.search(r"sidebar|side-?bar|topbar|header|nav|global.?search",
                             f"{region} {x.get('selector')} {hint}", re.I))


def is_table_row_control(x: dict) -> bool:
    """Row / bulk selection checkboxes in a table are not form-schema fill targets."""
    t = (x.get("type") or "").lower()
    if t not in ("checkbox", "radio"):
        return False
    if x.get("in_table") or x.get("table_row"):
        return True
    hint = _field_hint(x)
    sel = x.get("selector") or ""
    return bool(re.search(r"tbody|\[role=row\]|row-?check|select-?all|bulk", f"{sel} {hint}", re.I)
                and not x.get("required"))


def keep_form_field(x: dict) -> bool:
    """Whether a discovered control belongs in a form schema / fill plan."""
    return bool(x.get("selector")) and not is_chrome_search_field(x) and not is_table_row_control(x)


def record_control_fallback(note: str, *, how: str = "force") -> dict:
    """Record that a forced click / DOM set was used. Fallback never proves normal user actionability."""
    return {"fallback": True, "how": how, "note": (note or "")[:200],
            "proves_user_actionability": False}


def set_choice(el, *, checked: bool = True, log: list | None = None) -> dict:
    """Tick/untick a checkbox or radio the way a person would; force/DOM only as recorded fallback.

    Prefers a normal check/click. On failure tries force=True, then a DOM click. Any fallback is appended to
    `log` (when given) and returned with proves_user_actionability=False.
    """
    want = bool(checked)
    try:
        if want:
            el.check(timeout=3000)
        else:
            el.uncheck(timeout=3000)
        if bool(el.is_checked()) == want:
            return {"fallback": False, "how": "user", "proves_user_actionability": True}
    except Exception:
        pass
    try:
        if want:
            el.check(timeout=3000, force=True)
        else:
            el.uncheck(timeout=3000, force=True)
        if bool(el.is_checked()) == want:
            rec = record_control_fallback("force check/uncheck on styled control", how="force")
            if log is not None:
                log.append(rec)
            return rec
    except Exception:
        pass
    el.evaluate("(e, w) => { if (!!e.checked !== w) e.click(); }", want)
    if bool(el.is_checked()) != want:
        raise AssertionError("custom checkbox/radio did not retain the intended checked state")
    rec = record_control_fallback("DOM click on overlay-styled control", how="dom")
    if log is not None:
        log.append(rec)
    return rec


def select_option_user(el, value: str, *, log: list | None = None) -> dict:
    """Select a native <select> option; verify the value stuck. Force/DOM only as recorded fallback."""
    try:
        el.select_option(value, timeout=5000)
        if el.input_value() == value:
            return {"fallback": False, "how": "user", "proves_user_actionability": True}
    except Exception:
        pass
    try:
        el.evaluate(
            """(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true}));
               e.dispatchEvent(new Event('change', {bubbles: true})); }""",
            value,
        )
        if el.input_value() == value:
            rec = record_control_fallback("DOM value set on select", how="dom")
            if log is not None:
                log.append(rec)
            return rec
    except Exception as e:
        raise AssertionError(f"select option {value!r} was not retained: {e}") from e
    raise AssertionError(f"dropdown value {value!r} was not retained after user and fallback paths")


def reresolve_field(page, scope, box: dict):
    """Re-resolve a field after a reactive update (Vue/React re-render). Same uniqueness rules as unique_field."""
    return unique_field(page, scope, box)


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
            from .actions import action_class as _action_class
            submit_cls = _action_class(said, submit.get("selector") or "",
                                       role="button", kind="button", tag="button")
            if not submit.get("selector") or submit_cls == "pay" or submit_cls == "delete" \
                    or DELETE.search(said):
                continue  # (never a form that pays or deletes - not even with wrong values)
            fields = [dict(known.get(x["selector"], {}), **x) for x in f.get("fields", []) if x.get("selector")]
            fields = [x for x in fields if keep_form_field(x)]
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
                              "type": (x.get("type") or "").lower(), "tag": x.get("tag") or "",
                              "required": bool(x.get("required")),
                              "label": (x.get("label") or x.get("accname") or "")[:80],
                              "role": x.get("role") or "",
                              "valid": valid_value(x, "{tag}") if kind else "",
                              "tagged": kind in ("names", "text", "email")})
            required_boxes = [b for b in boxes if b["required"]]
            out.append({"page": p, "form": f, "boxes": boxes, "name": _form_name(p, f),
                        "openers": opener_path(p, f["selector"], f.get("revealed_by")),
                        "required_fields": [{"selector": b["selector"], "name": b["name"], "kind": b["kind"]}
                                            for b in required_boxes]})
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
            "submit_text": f["submit"].get("text") or "", "boxes": d["boxes"],
            "required_fields": d.get("required_fields") or [b for b in d["boxes"] if b.get("required")],
            "openers": d.get("openers") or []}


def form_scope(page, F: dict):
    """The form / dialog / labeled section that owns the fields (never the whole page chrome)."""
    sel = (F or {}).get("form") or (F or {}).get("selector") or ""
    if not sel:
        # No silent whole-page fallback when a form case forgot its container — fail closed.
        raise form_target_problem(
            "missing_required",
            "form container is missing from the case - not interacting with the whole page",
        )
    loc = page.locator(sel)
    count = loc.count()
    if count == 1:
        return loc.nth(0)
    if count == 0:
        raise form_target_problem("missing_required", f"form container {sel!r} is not on the page")
    # Prefer a visible dialog/section among duplicates; still fail closed when more than one remains.
    visible = [i for i in range(count) if loc.nth(i).is_visible()]
    if len(visible) == 1:
        return loc.nth(visible[0])
    raise form_target_problem(
        "ambiguous",
        f"form container {sel!r} matched {count} elements and could not be disambiguated - not interacting",
    )


def _visible_matches(locator) -> list:
    out = []
    try:
        n = locator.count()
    except Exception:
        return out
    for i in range(n):
        el = locator.nth(i)
        try:
            if el.is_visible():
                out.append(el)
        except Exception:
            continue
    return out


def unique_field(page, scope, box: dict):
    """Exactly one visible, relevant control inside the form container.

    Prefers stable id / recorded selector, then accessible name (label/role). Never uses .first to hide
    multiple matches: unresolved ambiguity raises FormTargetProblem(kind='ambiguous').
    """
    name = (box.get("name") or box.get("label") or "").strip()
    sel = box.get("selector") or ""
    attempts: list[tuple[str, object]] = []
    if sel:
        attempts.append(("selector", scope.locator(sel)))
    if name:
        attempts.append(("label", scope.get_by_label(name, exact=True)))
        role = (box.get("role") or "").strip()
        if role:
            attempts.append(("role", scope.get_by_role(role, name=name, exact=True)))
        if (box.get("type") or "").lower() in ("", "text", "email", "tel", "search", "url", "password", "number"):
            attempts.append(("textbox", scope.get_by_role("textbox", name=name, exact=True)))
        if (box.get("kind") or "") == "email" or (box.get("type") or "").lower() == "email":
            attempts.append(("email", scope.locator('input[type=email]')))
        if (box.get("kind") or "") == "phone" or (box.get("type") or "").lower() == "tel":
            attempts.append(("phone", scope.locator('input[type=tel], input[autocomplete=tel]')))
    for how, loc in attempts:
        found = _visible_matches(loc)
        if len(found) == 1:
            return found[0]
        if len(found) > 1 and how == "selector":
            # Same selector in the container more than once: try label within those matches only next.
            continue
        if len(found) > 1:
            raise form_target_problem(
                "ambiguous",
                f"'{name or sel}' matched {len(found)} visible controls via {how} inside the form - "
                "not interacting (fail closed)",
            )
    # Last resort: recorded selector on the page, still require uniqueness inside the scope's subtree check.
    if sel:
        page_hits = _visible_matches(page.locator(sel))
        if len(page_hits) == 1:
            # Confirm it sits inside the intended container when the container exists.
            try:
                inside = scope.locator(sel)
                if inside.count() == 1 and inside.nth(0).is_visible():
                    return inside.nth(0)
            except FormTargetProblem:
                raise
            except Exception:
                pass
            # Field only found outside the declared container — never grab page.first / off-scope hits.
            raise form_target_problem(
                "missing_required" if box.get("required") else "missing_optional",
                f"recorded field '{name or sel}' is visible on the page but not inside the form container",
            )
        if len(page_hits) > 1:
            raise form_target_problem(
                "ambiguous",
                f"'{name or sel}' matched {len(page_hits)} visible controls on the page and the form "
                "container could not disambiguate - not interacting (fail closed)",
            )
    kind = "missing_required" if box.get("required") else "missing_optional"
    raise form_target_problem(kind, f"recorded field '{name or sel}' is not visible inside the form")


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
                # Submitted (or write-guard "would send") outcomes are business credit; never auto-enabled by env=test.
                "verification": "business"}
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
                    "files": ["test_forms.py"], "tests": [f"test_{cid}"], "verification": "business",
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

# Playwright test template string (not SQL). Bandit S608 fires on "select … {value}" inside the body.
FORM_HELPERS = OPEN_PATH_HELPER + (  # noqa: S608
    r'''
class FormTargetProblem(Exception):
    """Ambiguous or missing form target - never silently pick one match with .first."""
    kind = 'missing_optional'


def _form_target_problem(kind, message):
    err = FormTargetProblem(message)
    err.kind = kind
    return err


def _visible(loc):
    try:
        return loc.count() == 1 and loc.nth(0).is_visible()
    except Exception:
        return False


def _visible_matches(locator):
    out = []
    try:
        n = locator.count()
    except Exception:
        return out
    for i in range(n):
        el = locator.nth(i)
        try:
            if el.is_visible():
                out.append(el)
        except Exception:
            continue
    return out


def _form_scope(page, F):
    """The form / dialog / labeled section that owns the fields (never page chrome)."""
    sel = (F or {}).get('form') or (F or {}).get('selector') or ''
    if not sel:
        raise _form_target_problem(
            'missing_required',
            'form container is missing from the case - not interacting with the whole page')
    loc = page.locator(sel)
    count = loc.count()
    if count == 1:
        return loc.nth(0)
    if count == 0:
        raise _form_target_problem('missing_required', f'form container {sel!r} is not on the page')
    visible = [i for i in range(count) if loc.nth(i).is_visible()]
    if len(visible) == 1:
        return loc.nth(visible[0])
    raise _form_target_problem(
        'ambiguous',
        f'form container {sel!r} matched {count} elements and could not be disambiguated - not interacting')


def _unique_field(page, scope, box):
    """Exactly one visible control inside the form. Prefer label / role / recorded selector; never .first on many."""
    name = (box.get('name') or box.get('label') or '').strip()
    sel = box.get('selector') or ''
    attempts = []
    if sel:
        attempts.append(('selector', scope.locator(sel)))
    if name:
        attempts.append(('label', scope.get_by_label(name, exact=True)))
        role = (box.get('role') or '').strip()
        if role:
            attempts.append(('role', scope.get_by_role(role, name=name, exact=True)))
        if (box.get('type') or '').lower() in ('', 'text', 'email', 'tel', 'search', 'url', 'password', 'number'):
            attempts.append(('textbox', scope.get_by_role('textbox', name=name, exact=True)))
        if (box.get('kind') or '') == 'email' or (box.get('type') or '').lower() == 'email':
            attempts.append(('email', scope.locator('input[type=email]')))
        if (box.get('kind') or '') == 'phone' or (box.get('type') or '').lower() == 'tel':
            attempts.append(('phone', scope.locator('input[type=tel], input[autocomplete=tel]')))
    for how, loc in attempts:
        found = _visible_matches(loc)
        if len(found) == 1:
            return found[0]
        if len(found) > 1 and how == 'selector':
            continue
        if len(found) > 1:
            raise _form_target_problem(
                'ambiguous',
                f"'{name or sel}' matched {len(found)} visible controls via {how} inside the form - "
                'not interacting (fail closed)')
    if sel:
        page_hits = _visible_matches(page.locator(sel))
        if len(page_hits) == 1:
            inside = scope.locator(sel)
            if inside.count() == 1 and inside.nth(0).is_visible():
                return inside.nth(0)
            raise _form_target_problem(
                'missing_required' if box.get('required') else 'missing_optional',
                f"recorded field '{name or sel}' is visible on the page but not inside the form container")
        if len(page_hits) > 1:
            raise _form_target_problem(
                'ambiguous',
                f"'{name or sel}' matched {len(page_hits)} visible controls on the page and the form "
                'container could not disambiguate - not interacting (fail closed)')
    kind = 'missing_required' if box.get('required') else 'missing_optional'
    raise _form_target_problem(kind, f"recorded field '{name or sel}' is not visible inside the form")


def _record_control_fallback(note, how='force'):
    """Forced click / DOM set: recorded, never counts as proving normal user actionability."""
    return {'fallback': True, 'how': how, 'note': (note or '')[:200], 'proves_user_actionability': False}


def _set_choice(el, checked=True, log=None):
    """User-facing check first; force/DOM only as recorded fallback. Verifies checked state."""
    want = bool(checked)
    try:
        if want:
            el.check(timeout=3000)
        else:
            el.uncheck(timeout=3000)
        if bool(el.is_checked()) == want:
            return {'fallback': False, 'how': 'user', 'proves_user_actionability': True}
    except Exception:
        pass
    try:
        if want:
            el.check(timeout=3000, force=True)
        else:
            el.uncheck(timeout=3000, force=True)
        if bool(el.is_checked()) == want:
            rec = _record_control_fallback('force check/uncheck on styled control', 'force')
            if log is not None:
                log.append(rec)
            return rec
    except Exception:
        pass
    el.evaluate('(e, w) => { if (!!e.checked !== w) e.click(); }', want)
    if bool(el.is_checked()) != want:
        raise AssertionError('custom checkbox/radio did not retain the intended checked state')
    rec = _record_control_fallback('DOM click on overlay-styled control', 'dom')
    if log is not None:
        log.append(rec)
    return rec


def _select_option_user(el, value, log=None):
    try:
        el.select_option(value, timeout=5000)
        if el.input_value() == value:
            return {'fallback': False, 'how': 'user', 'proves_user_actionability': True}
    except Exception:
        pass
    el.evaluate(
        "(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true}));"
        " e.dispatchEvent(new Event('change', {bubbles: true})); }", value)
    if el.input_value() == value:
        rec = _record_control_fallback('DOM value set on select', 'dom')
        if log is not None:
            log.append(rec)
        return rec
    raise AssertionError(f'dropdown value {value!r} was not retained after user and fallback paths')


def _reresolve_field(page, scope, box):
    """Re-resolve after reactive re-renders (same uniqueness rules)."""
    return _unique_field(page, scope, box)


def _fill_form(page, F, tag, bad=None):
    """A valid value in every box scoped to the form - except `bad`: (selector, value).

    Required fields that are missing/invisible fail the whole form. Optional fields need an explicit skip reason.
    Ambiguous targets raise FormTargetProblem (automation/inconclusive), never a quiet .first pick.
    """
    scope = _form_scope(page, F)
    groups = set()
    intended = list(F.get('required_fields') or [b for b in F['boxes'] if b.get('required')])
    filled_required = set()
    for b in F['boxes']:
        try:
            el = _unique_field(page, scope, b)
        except FormTargetProblem as e:
            if e.kind == 'ambiguous':
                raise
            if b.get('required') or e.kind == 'missing_required':
                raise AssertionError(
                    f"required field '{b.get('name') or b.get('selector')}' is missing or invisible - "
                    f"whole-form check cannot pass ({e})") from e
            _step_ok(f"skipped optional '{b.get('name') or b.get('selector')}': {e}")
            continue
        if not el.is_enabled():  # (greyed out now - a return date of a one-way trip): a person leaves it
            if bad and b['selector'] == bad[0]:
                raise AssertionError(
                    f"'{b['name']}' is disabled on this page - nothing can be typed into it"
                    + (" (required for this check)" if b.get('required') else ""))
            if b.get('required'):
                raise AssertionError(
                    f"required field '{b['name']}' is disabled/invisible to typing - whole-form check cannot pass")
            _step_ok(f"skipped optional '{b['name']}': disabled on this page (conditional)")
            continue
        if bad and b['selector'] == bad[0]:
            el.fill(bad[1])
            if b.get('required'):
                filled_required.add(b['selector'])
            continue
        if b['type'] == 'checkbox':
            if b['required']:
                _set_choice(el, checked=True)
                el = _reresolve_field(page, scope, b)
                if not el.is_checked():
                    raise AssertionError(f"required checkbox '{b['name']}' did not stay checked")
                filled_required.add(b['selector'])
            continue
        if b['type'] == 'radio':
            name = el.get_attribute('name') or b['selector']
            if name not in groups:
                groups.add(name)
                # (a choice that is already made - 'Round trip' - is kept, like a person would)
                if not scope.locator(f'input[type=radio][name="{name}"]:checked').count():
                    _set_choice(el, checked=True)
                    el = _reresolve_field(page, scope, b)
                    if not el.is_checked():
                        raise AssertionError(f"radio '{b['name']}' did not stay selected")
                if b.get('required'):
                    filled_required.add(b['selector'])
            continue
        if b['tag'] == 'select' or b['type'].startswith('select'):
            options = el.evaluate("e => [...e.options].filter(o => !o.disabled && o.value).map(o => o.value)")
            if options and not el.input_value():
                _select_option_user(el, options[0])
                el = _reresolve_field(page, scope, b)
                if el.input_value() != options[0]:
                    raise AssertionError(f"select '{b['name']}' did not retain option {options[0]!r}")
            if b.get('required'):
                filled_required.add(b['selector'])
            continue
        if b['type'] == 'file' or not b['kind']:
            if b.get('required') and b['type'] != 'file':
                raise AssertionError(
                    f"required field '{b['name']}' has no field kind / value plan - whole-form check cannot pass")
            if b.get('required') and b['type'] == 'file':
                raise AssertionError(
                    f"required file field '{b['name']}' cannot be filled here - whole-form check cannot pass")
            if not b['kind']:
                _step_ok(f"skipped optional '{b['name']}': no typed value kind")
            continue
        value = b['valid']
        if b['kind'] == 'email':
            value = f"{tag}@example.com"
        elif b['kind'] == 'phone' and not value:
            value = '+1 555 010 0199'
        elif b['tagged']:
            value = value.replace('{tag}', tag)
        el.fill(value)
        el = _reresolve_field(page, scope, b)
        expect(el, "The input must retain its intended test value").to_have_value(value)
        if b.get('required'):
            filled_required.add(b['selector'])
    missing = [r for r in intended if (r.get('selector') if isinstance(r, dict) else r) not in filled_required
               and (r.get('selector') if isinstance(r, dict) else r) not in {(bad or [None])[0]}]
    # Radios/checkboxes/selects already counted; typed required boxes must have been filled.
    typed_missing = []
    for r in missing:
        sel = r.get('selector') if isinstance(r, dict) else r
        box = next((b for b in F['boxes'] if b['selector'] == sel), None)
        if not box or box.get('type') in ('checkbox', 'radio') or box.get('tag') == 'select':
            continue
        if bad and sel == bad[0]:
            continue
        typed_missing.append(box.get('name') or sel)
    if typed_missing:
        raise AssertionError(
            "required field(s) not filled - whole-form check cannot pass: " + ", ".join(typed_missing))


def _send(page, F):
    """Click the form's own button (this one planned click is approved; on test / production the write guard stops
    what it sends). Prefer the button inside the form container; fail closed if ambiguous."""
    scope = _form_scope(page, F)
    btn_loc = scope.locator(F['submit'])
    found = _visible_matches(btn_loc)
    if not found:
        found = _visible_matches(page.locator(F['submit']))
    if len(found) != 1:
        raise _form_target_problem(
            'ambiguous' if len(found) > 1 else 'missing_required',
            f"form submit {F['submit']!r} matched {len(found)} visible controls - not clicking")
    btn = found[0]
    expect(btn, 'the form\'s button should be visible').to_be_visible()
    btn.evaluate(APPROVE_JS)
    btn.click()
    page.wait_for_timeout(1200)
    _settle(page)


def _box_invalid(page, sel, scope=None):
    try:
        root = scope if scope is not None else page
        loc = root.locator(sel)
        found = _visible_matches(loc)
        if len(found) != 1:
            return False
        return bool(found[0].evaluate(
            "e => (e.matches && e.matches(':invalid')) || e.getAttribute('aria-invalid') === 'true'"))
    except Exception:
        return False


def _outcome(page, F, before, start, tried=None, box=None, scope=None):
    """What the form did: 'sent' (the page tried to send it - guard mode), 'refused' (an error / an invalid box),
    'accepted' (sent mode: another page or a success message, no error) or 'silent' (nothing visible happened)."""
    if tried is not None and tried:
        return 'sent', f"{tried[-1]['method']} {tried[-1]['path']}"
    found = page.evaluate(VALIDATION_JS, before)
    msgs = [m for m in _messages(page) if m not in before]
    bad = [m for m in msgs if _tone(m) == 'error']
    if found['message'] or found['marked'] or bad or (box and _box_invalid(page, box, scope)):
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
    target = F['boxes'][0]['selector'] if F.get('boxes') else F.get('form')
    if F.get('openers'):
        open_path(page, F['openers'], target)
    scope = _form_scope(page, F)
    _fill_form(page, F, tag, bad)
    before, start = page.evaluate(LINES_JS), page.url
    n = len(write_guard) if write_guard is not None else 0
    _send(page, F)
    tried = write_guard[n:] if write_guard is not None else None
    return _outcome(page, F, before, start, tried, bad[0] if bad else None, scope)


def _check_valid(page, F, tag, write_guard=None, track=None):
    try:
        what, how = _try_form(page, F, tag, write_guard)
    except FormTargetProblem as e:
        if e.kind == 'ambiguous':
            _inconclusive(str(e))
            return
        raise AssertionError(str(e)) from e
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
    try:
        for v in F['wrong']:
            what, how = _try_form(page, F, tag, write_guard, (F['box'], v['value']))
            seen.append((v['value'], what, how))
            if track and what == 'accepted':
                track('form', tag, F['url'])
        for v in F.get('either', []):
            what, how = _try_form(page, F, tag, write_guard, (F['box'], v['value']))
            _step_ok(f"'{F['box_name']}' = {v['value']!r} ({v['why']}): {what} - recorded, no rule either way")
    except FormTargetProblem as e:
        if e.kind == 'ambiguous':
            _inconclusive(str(e))
            return
        raise AssertionError(str(e)) from e
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
    if C.get('search'):
        search = page.locator(C['search'])
        hits = _visible_matches(search)
        if len(hits) == 1:
            hits[0].fill(text)
            page.wait_for_timeout(800)
    for _ in range(6):
        rows = page.locator('tr, li, [class*=card i], [class*=item i], [class*=row i]').filter(has_text=text)
        if rows.count() == 1:
            return rows.nth(0)
        if rows.count() > 1:
            return rows.nth(0)  # list rows sharing the tag text: the first matching row is the record
        nxt = page.locator('button:has-text("Next"), a:has-text("Next"), [rel=next]')
        nxt_hits = _visible_matches(nxt)
        if len(nxt_hits) != 1 or not nxt_hits[0].is_enabled():
            return None
        nxt_hits[0].click()
        page.wait_for_timeout(600)
    return None


def _delete_row(page, row, text_of_button):
    btn = row.locator(f'button:has-text("{text_of_button}"), a:has-text("{text_of_button}"), '
                      f'input[value="{text_of_button}"]')
    hits = _visible_matches(btn)
    assert len(hits) == 1, f"Delete control '{text_of_button}' matched {len(hits)} times on the row"
    hits[0].evaluate(APPROVE_JS)
    page.once('dialog', lambda d: d.accept())  # (staging + ALLOW_ACTIONS=delete: the confirm box is answered OK)
    hits[0].click()
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
        edit = row.locator('a, button').filter(has_text=re.compile(r'^\s*(edit|modify|change)', re.I))
        edit_hits = _visible_matches(edit)
        assert len(edit_hits) == 1, f"Edit control matched {len(edit_hits)} times on the row"
        edit_hits[0].click()
        _settle(page)
        scope = _form_scope(page, C)
        box = _unique_field(page, scope, {'selector': C['name_box'], 'name': 'name', 'required': True})
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
''')

# Real helpers (observe / offline tests) mirror the generated FORM_HELPERS above.
# Manual string (not getsource of form_target_problem) so generated scripts never contain a banned .__init__.
FIELD_TARGET_HELPERS = (
    inspect.getsource(FormTargetProblem)
    + "\n\n"
    + "def form_target_problem(kind, message):\n"
    + "    err = FormTargetProblem(message)\n"
    + "    err.kind = kind\n"
    + "    return err\n\n"
    + inspect.getsource(form_scope)
    + "\n"
    + inspect.getsource(_visible_matches)
    + "\n"
    + inspect.getsource(unique_field)
    + "\n"
    + inspect.getsource(record_control_fallback)
    + "\n"
    + inspect.getsource(set_choice)
    + "\n"
    + inspect.getsource(select_option_user)
    + "\n"
    + inspect.getsource(reresolve_field)
    + "\n"
)


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
