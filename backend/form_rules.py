"""Rules BETWEEN fields - what a tester checks beyond one box at a time (Step 7):

  date range      two date boxes from/to, start/end, depart(ure)/return, check-in/check-out, pickup/drop
                  -> the end before the start is refused (an error, the date can't be picked, the search is blocked)
  past date       a booking / search date (depart, check-in, travel, pickup, appointment, delivery) -> yesterday refused
  same value      two boxes of the same kind with the same choices (from/to, origin/destination, source/target,
                  pickup/drop, from account/to account) -> the same value in both is refused
  min / max       two number boxes min/max, from/to price, low/high -> min > max refused
  confirm         password + confirm / repeat / re-enter password, e-mail + confirm e-mail -> different values refused
  count -> total  passengers / adults / guests / quantity / rooms / nights / tickets / seats with a price or total on
                  the page -> 1 -> 2 changes the total; with a unit price shown: total = unit x count
  dependency      a disabled box next to a choice (One way / Round trip): one choice enables it, another disables it
  step order      a multi-step form (step 1 sent on staging led to step 2's form, or ?step=2 / /step-2 in a page's
                  address): step 2 opened directly as a NEW visitor -> its form is not offered (sent back / refused)
                  (public steps only: a logged-in session may still remember step 1, so it would prove nothing)

They are COMMON CONVENTIONS, not the website's written rules: a broken one is a `rule_violation` finding (medium) - a
question in the review ("The site accepted a return date before the departure date. Is that allowed?"); a confirmed
answer makes it a product defect (or removes it) for the next run. Detection is by words (English first), types and
choices; the AI may only SUGGEST pairs (ask_structured -> FieldRule, field ids that must exist) - these rules decide
which tests are made. Without sending data (test / production) a pair test uses the write guard for every form but a
GET form: a form without a method sends with script (OrangeHRM's 'Change Password' was sent for real once). A GET
search form is sent normally (it only reads).
"""
import re
from pprint import pformat
from urllib.parse import urlparse

from pydantic import BaseModel

from .actions import writes_allowed

RULES = ("date_range", "past_date", "same_value", "min_max", "confirm", "count_total", "dependency")
START = r"\b(from|start|begin|depart(ure)?|check-?in|pick-?up|outbound|arrival|since)\b"
END = r"\b(to|until|end|return|check-?out|drop(-?off)?|inbound|departure back|back)\b"
BOOKING_DATE = re.compile(r"depart|check-?in|travel|pick-?up|appointment|delivery|journey|flight|start", re.I)
SAME_PAIRS = [(r"\bfrom\b|origin|source|leaving|departure (city|airport)", r"\bto\b|destination|target|going|arrival (city|airport)"),
              (r"pick-?up", r"drop(-?off)?"), (r"from account", r"to account")]
MINMAX = [(r"\bmin(imum)?\b|\blow(est)?\b|price from|\bfrom\b", r"\bmax(imum)?\b|\bhigh(est)?\b|price to|\bto\b")]
CONFIRM = re.compile(r"confirm|repeat|re-?enter|again|verify|retype", re.I)
CURRENT = re.compile(r"current|\bold\b|existing|present", re.I)  # 'Current Password' is checked against the account
COUNT = re.compile(r"passengers?|adults?|children|guests?|quantity|\bqty\b|rooms?|nights?|tickets?|seats?|travell?ers?|people",
                   re.I)


class FieldRule(BaseModel):
    """An AI suggestion: a rule between two boxes of one form (their ids must exist on the page)."""
    rule: str
    fields: list[str]


def _hint(b: dict) -> str:
    return " ".join(str(b.get(k) or "") for k in ("label", "placeholder", "name", "id", "accname")).lower()


def _is_date(b: dict) -> bool:
    return (b.get("type") or "") in ("date", "datetime-local", "month") or bool(
        re.search(r"\bdate\b|\bdd/mm|mm/dd|yyyy", _hint(b)))


def _groups(p: dict) -> list[dict]:
    """The boxes that belong together: each form, else every box of the page (a search panel without a <form>)."""
    by_sel = {i.get("selector"): i for i in p.get("inputs", []) if i.get("selector")}
    out = []
    for f in p.get("forms", []):
        boxes = [dict(by_sel.get(x["selector"], {}), **x) for x in f.get("fields", []) if x.get("selector")]
        if len(boxes) >= 2:
            out.append({"form": f, "boxes": boxes})
    if not out:
        boxes = [i for i in p.get("inputs", []) if i.get("selector") and not i.get("readonly")]
        if len(boxes) >= 2:
            out.append({"form": None, "boxes": boxes})
    return out


def _pairs_in(boxes: list[dict]) -> list[tuple[str, dict, dict]]:
    found = []
    dates = [b for b in boxes if _is_date(b)]
    starts = [b for b in dates if re.search(START, _hint(b))]
    ends = [b for b in dates if re.search(END, _hint(b)) and b not in starts]
    if starts and ends:
        found.append(("date_range", starts[0], ends[0]))
    for b in dates:
        if BOOKING_DATE.search(_hint(b)) and b not in ends:
            found.append(("past_date", b, b))
            break
    for a_rx, b_rx in SAME_PAIRS:
        a = next((b for b in boxes if re.search(a_rx, _hint(b)) and not _is_date(b)), None)
        b = next((x for x in boxes if re.search(b_rx, _hint(x)) and not _is_date(x) and x is not a), None)
        if a and b and (a.get("tag") == b.get("tag")) and _same_kind(a, b):
            found.append(("same_value", a, b))
            break
    nums = [b for b in boxes if (b.get("type") or "") == "number" or re.search(r"price|amount|budget", _hint(b))]
    for a_rx, b_rx in MINMAX:
        a = next((b for b in nums if re.search(a_rx, _hint(b))), None)
        b = next((x for x in nums if re.search(b_rx, _hint(x)) and x is not a), None)
        if a and b and not COUNT.search(_hint(a)):
            found.append(("min_max", a, b))
    for kind in ("password", "email"):
        same = [b for b in boxes if (b.get("type") or "") == kind or (kind == "email" and "mail" in _hint(b))]
        conf = [b for b in same if CONFIRM.search(_hint(b))]
        main = [b for b in same if b not in conf and not CURRENT.search(_hint(b))]  # (the NEW password is confirmed)
        if main and conf:
            found.append(("confirm", main[0], conf[0]))
    return found


def _same_kind(a: dict, b: dict) -> bool:
    """Two boxes that take the same kind of value: the same choices (two airport lists), or two text boxes."""
    oa, ob = [o.get("value") for o in a.get("options") or []], [o.get("value") for o in b.get("options") or []]
    if oa or ob:
        return bool(oa) and set(oa) == set(ob)
    return (a.get("type") or "text") == (b.get("type") or "text")


def _count_total(p: dict, boxes: list[dict]) -> tuple[dict, bool] | None:
    """A count box (passengers, guests, tickets ...) on a page that SHOWS a total ("Estimated total: $120") - a
    product page's quantity box next to the item's price is not one (its price stays the unit price); the cart's own
    lines have their own tests."""
    if p.get("page_type") == "cart" or not p.get("totals"):
        return None
    count = next((b for b in boxes if COUNT.search(_hint(b)) and ((b.get("type") or "") == "number"
                                                                 or b.get("tag") == "select")), None)
    return (count, True) if count else None


def _dependency(p: dict, boxes: list[dict]) -> tuple[dict, list[dict]] | None:
    """A disabled box next to a group of choices (One way / Round trip enables the return date)."""
    off = next((b for b in boxes if b.get("disabled")), None)
    radios = [b for b in boxes if (b.get("type") or "") == "radio"]
    if off and len(radios) >= 2:
        return off, radios
    return None


def pair_cases(pages: list[dict], suggestions: list[dict] | None = None) -> list[dict]:
    """One test case per detected rule (each links to both boxes in the registry)."""
    out, seen = [], set()
    guard = not writes_allowed()
    for p in pages:
        for g in _groups(p):
            f, boxes = g["form"], g["boxes"]
            reads = (f or {}).get("method") == "get"  # (post, 'script' and a panel without a form may write)
            submit = ((f or {}).get("submit") or {}).get("selector")
            if not submit and f is None:
                submit = next((b["selector"] for b in p.get("buttons", []) if b.get("selector") and
                               re.search(r"search|find|go|book|continue|next|submit", b.get("text") or "", re.I)), None)
            rules = _pairs_in(boxes)
            for s in suggestions or []:  # the AI's suggestions: only for boxes that really exist here
                a = next((b for b in boxes if b.get("id") == s["fields"][0] or b.get("name") == s["fields"][0]), None)
                b = next((x for x in boxes if len(s["fields"]) > 1 and (x.get("id") == s["fields"][1] or
                                                                         x.get("name") == s["fields"][1])), a)
                if a and b and s["rule"] in RULES and not any(r[0] == s["rule"] for r in rules):
                    rules.append((s["rule"], a, b))
            ct = _count_total(p, boxes)
            if ct:
                rules.append(("count_total", ct[0], ct[0]))
            dep = _dependency(p, boxes)
            if dep:
                rules.append(("dependency", dep[0], dep[1][0]))
            for rule, a, b in rules:
                key = (rule, a["selector"], b["selector"])
                if key in seen or (a is not b and a["selector"] == b["selector"]):
                    continue  # (one address for both boxes: the test would type both values into the same box)
                seen.add(key)
                out.append(_case(len(out) + 1, rule, p, f, a, b, submit, guard and not reads,
                                 radios=[x["selector"] for x in (dep[1] if dep and rule == "dependency" else [])],
                                 boxes=boxes))
    return out


STEP_IN_ADDRESS = re.compile(r"(?:[?&](?:step|stage)=|/step[-_/]?)(\d+)", re.I)


def step_order_cases(pages: list[dict]) -> list[dict]:
    """A later step of a multi-step form, opened directly by a new visitor (step 1 never done): its form must not be
    offered. The steps come from exploring - a form sent on staging that led to another form - and from addresses
    with a step number above 1. A step that IS offered is a question ("Is that allowed?"), not a proven bug."""
    from .agents.change_detection import page_key
    by_key = {page_key(p["url"]): p for p in pages}
    chains = []
    for p in pages:
        for rec in p.get("form_fills") or []:
            nxt = by_key.get(page_key(rec.get("next_url") or "")) if rec.get("sent") and rec.get("next_url") else None
            if nxt and nxt is not p:
                chains.append((p, nxt, rec.get("name") or "the form"))
    for p in pages:
        m = STEP_IN_ADDRESS.search(p["url"])
        if m and int(m.group(1)) > 1:
            chains.append((None, p, None))
    out, seen = [], set()
    for first, step, sent_by in chains:
        form = next((f for f in step.get("forms") or [] if any(x.get("selector") for x in f.get("fields") or [])), None)
        fields = [x["selector"] for x in (form or {}).get("fields") or []
                  if x.get("selector") and (x.get("type") or "") not in ("hidden", "submit", "button", "image")][:8]
        if not fields or step.get("auth") or (first or {}).get("auth") or page_key(step["url"]) in seen:
            continue
        seen.add(page_key(step["url"]))
        name = (step.get("title") or page_key(step["url"]))[:60]
        before = f"'{sent_by}' on {page_key(first['url'])}" if first else "the step before it"
        n = len(out) + 1
        spec = {"url": step["url"], "rule": "step_order", "fields": fields, "form": form.get("selector"),
                "a": "", "b": "", "a_name": before, "b_name": name, "submit": "", "guard": False, "radios": [],
                "question": f"The site offered the step '{name}' of a multi-step form to a new visitor who never did "
                            f"{before}. Is that allowed?", "others": []}
        out.append({"id": f"pair_step_{n}", "kind": "pair", "type": "negative", "priority": "medium",
                    "title": f"Rule: the step '{name}' is not offered without {before} ({urlparse(step['url']).path or '/'})",
                    "steps": [f"As a new visitor (step 1 never done), open {step['url']} directly",
                              "Look whether the step's form can be filled in"],
                    "expected": "Not offered: the website sends you to the first step, or says to start again",
                    "page": step["slug"], "url": step["url"], "pages": [step["slug"]], "guest": True, "test_data": "",
                    "oracle": "convention", "feature": "Multi-step form", "element": f"the steps: {before} -> '{name}'",
                    "files": ["test_field_rules.py"], "tests": [f"test_pair_step_{n}"], "spec": spec})
    return out


TITLES = {"date_range": "'{b}' before '{a}' is refused", "past_date": "a date in the past in '{a}' is refused",
          "same_value": "the same value in '{a}' and '{b}' is refused", "min_max": "'{a}' above '{b}' is refused",
          "confirm": "'{b}' different from '{a}' is refused", "count_total": "changing '{a}' changes the total",
          "dependency": "a choice enables / disables '{a}'"}
QUESTION = {"date_range": "The site accepted '{b}' before '{a}'. Is that allowed?",
            "past_date": "The site accepted a date in the past in '{a}'. Is that allowed?",
            "same_value": "The site accepted the same value in '{a}' and '{b}'. Is that allowed?",
            "min_max": "The site accepted '{a}' larger than '{b}'. Is that allowed?",
            "confirm": "The site accepted a '{b}' that differs from '{a}'. Is that allowed?",
            "count_total": "Changing '{a}' did not change the total as expected. Is that right?",
            "dependency": "No choice enabled '{a}'. Is that right?"}


def _name(b: dict) -> str:
    return (b.get("label") or b.get("placeholder") or b.get("name") or b.get("id") or "box").split("\n")[0].strip()[:40]


def _others(boxes: list[dict], a: dict, b: dict) -> list[dict]:
    """Valid values for the form's OTHER required boxes: then the pair is the only thing wrong in the form, and a
    refusal is about the rule - not about an empty 'Full name' next to it."""
    from .testdata import valid_value
    out = []
    for x in boxes:
        t = (x.get("type") or "").lower()
        if x["selector"] in (a["selector"], b["selector"]) or not x.get("required") or x.get("disabled") \
                or t in ("file", "hidden", "submit", "button", "image"):
            continue
        if t in ("checkbox", "radio"):
            out.append({"selector": x["selector"], "tick": True})
        elif (v := valid_value(x)):
            out.append({"selector": x["selector"], "value": v})
    return out[:12]


def _case(n: int, rule: str, p: dict, f: dict | None, a: dict, b: dict, submit: str | None, guarded: bool,
          radios: list | None = None, boxes: list | None = None) -> dict:
    an, bn = _name(a), _name(b)
    title = TITLES[rule].format(a=an, b=bn)
    spec = {"url": p["url"], "rule": rule, "a": a["selector"], "b": b["selector"], "a_name": an, "b_name": bn,
            "a_type": a.get("type") or a.get("tag") or "", "b_type": b.get("type") or b.get("tag") or "",
            "submit": submit, "form": (f or {}).get("selector"), "guard": guarded, "radios": radios or [],
            "question": QUESTION[rule].format(a=an, b=bn), "pair": [a["selector"], b["selector"]],
            "others": _others(boxes or [], a, b)}
    return {"id": f"pair_{n}", "kind": "pair", "type": "negative" if rule not in ("count_total", "dependency")
            else "positive", "priority": "medium", "title": f"Rule: {title} ({urlparse(p['url']).path or '/'})",
            "steps": [f"Open {p['url']}", STEPS[rule].format(a=an, b=bn)] + (["Send the form" if submit else
                                                                               "Look at the page"]),
            "expected": EXPECTED[rule].format(a=an, b=bn), "page": p["slug"], "url": p["url"], "pages": [p["slug"]],
            "guest": not p.get("auth"), "test_data": "", "oracle": "convention",
            "files": ["test_field_rules.py"], "tests": [f"test_pair_{n}"], "spec": spec}


STEPS = {"date_range": "Pick a '{b}' 5 days BEFORE the '{a}'", "past_date": "Pick yesterday in '{a}'",
         "same_value": "Choose the same value in '{a}' and '{b}'", "min_max": "Type a '{a}' larger than the '{b}'",
         "confirm": "Type different values in '{a}' and '{b}'", "count_total": "Change '{a}' from 1 to 2",
         "dependency": "Choose each option next to '{a}'"}
EXPECTED = {"date_range": "Refused: an error, the date can't be picked, or the search is blocked",
            "past_date": "Refused or not selectable", "same_value": "Refused, or no results with a message",
            "min_max": "Refused or no results", "confirm": "Refused with an error",
            "count_total": "The total changes; with a unit price shown: total = unit x count (+ fees shown)",
            "dependency": "One choice enables it, another disables it"}


RULE_HELPERS = r'''
from datetime import date, timedelta


def _set(page, sel, value):
    el = page.locator(sel).first
    if el.evaluate("e => e.tagName") == 'SELECT':
        el.select_option(value)
    else:
        el.fill(str(value))


def _options_of(page, sel):
    return [v for v in page.locator(sel).first.evaluate(
        "e => e.tagName === 'SELECT' ? [...e.options].filter(o => !o.disabled && o.value).map(o => o.value) : []") if v]


def _refused(page, R, before, start, tried):
    """Did the site refuse what was sent? (an error / an invalid box / nothing sent and no results page)"""
    if tried:
        return False, f"it would send {tried[-1]['method']} {tried[-1]['path']}"
    found = page.evaluate(VALIDATION_JS, before)
    bad = [m for m in _messages(page) if m not in before and _tone(m) == 'error']
    invalid = [s for s in (R['a'], R['b']) if _invalid(page, s)]
    if found['message'] or found['marked'] or bad or invalid:
        return True, found['message'] or (bad[0] if bad else f'{len(invalid)} box(es) marked invalid')
    ok = [m for m in _messages(page) if m not in before and _tone(m) == 'ok']
    if ok:  # (the site answered on the same address: 'Account created')
        return False, f'the site said {ok[0]!r}'
    if page.url.split('#')[0] == start.split('#')[0]:
        return True, 'the page stayed where it was (nothing was sent)'
    return False, f'it went on to {page.url}'


def _invalid(page, sel):
    try:
        return bool(page.locator(sel).first.evaluate(
            "e => (e.matches && e.matches(':invalid')) || e.getAttribute('aria-invalid') === 'true'"))
    except Exception:
        return False


def _go(page, R):
    before, start = page.evaluate(LINES_JS), page.url
    if R['submit']:
        btn = page.locator(R['submit']).first
        btn.evaluate(APPROVE_JS)
        btn.click()
    else:
        page.locator(R['b']).first.press('Enter')
    page.wait_for_timeout(1200)
    _settle(page)
    return before, start


def _rule_broken(R, how):
    """A common convention the site does not keep: a QUESTION (rule violation), not a proven bug - unless you answered
    in the review that it is NOT allowed (then it is a bug of the website)."""
    if R.get('confirmed'):
        raise AssertionError(f"[rule-confirmed] {R['question'].replace(' Is that allowed?', '')} - you said it is "
                             f"not allowed ({how})")
    raise AssertionError(f"[rule] {R['question']} ({how})")


def _money(text):
    return [float(m.replace(',', '')) for m in re.findall(r'[$€£₹]\s?(\d[\d,]*(?:\.\d{1,2})?)', text or '')]


def _check_rule(page, R, write_guard=None):
    page.goto(R['url'])
    _settle(page)
    rule = R['rule']
    if rule == 'step_order':  # a later step opened directly by a new visitor: its form must not be offered
        here, asked = page.url.split('#')[0].rstrip('/'), R['url'].split('#')[0].rstrip('/')
        shown = [s for s in R['fields'] if here == asked and page.locator(s).first.is_visible()]
        if len(shown) * 2 >= len(R['fields']):
            _rule_broken(R, f"{len(shown)} of the step's {len(R['fields'])} boxes were offered")
        _step_ok(f"not offered: {'sent to ' + page.url if here != asked else 'its form is not shown'}")
        assert len(shown) * 2 < len(R['fields'])
        return
    tried = write_guard if write_guard is not None else []
    n = len(tried)
    today = date.today()
    if rule in ('date_range', 'past_date'):
        a, b = page.locator(R['a']).first, page.locator(R['b']).first
        if rule == 'date_range':
            if b.is_disabled():  # (a return date that is only open for a round trip: open it like a person)
                choice = page.get_by_label(re.compile(r'round|return|two', re.I)).first
                if choice.count():
                    choice.check()
            a.fill((today + timedelta(days=20)).isoformat())
            b.fill((today + timedelta(days=15)).isoformat())
        else:
            a.fill((today - timedelta(days=1)).isoformat())
            if _invalid(page, R['a']):
                _step_ok(f"yesterday in '{R['a_name']}' is marked invalid / can't be picked")
                assert _invalid(page, R['a'])
                return
    elif rule == 'same_value':
        opts = _options_of(page, R['a'])
        value = opts[0] if opts else 'London'
        _set(page, R['a'], value)
        _set(page, R['b'], value)
    elif rule == 'min_max':
        _set(page, R['a'], '500')
        _set(page, R['b'], '100')
    elif rule == 'confirm':
        mail = 'mail' in R['a_type'] or 'mail' in R['a_name'].lower()
        _set(page, R['a'], 'qa.tester@example.com' if mail else 'Qa-Test#2026x')
        _set(page, R['b'], 'other.tester@example.com' if mail else 'Different#2026y')
    elif rule == 'count_total':
        _set(page, R['a'], '1')
        page.wait_for_timeout(600)
        one = _money(page.locator('body').inner_text())
        _set(page, R['a'], '2')
        page.wait_for_timeout(800)
        two = _money(page.locator('body').inner_text())
        if not one:
            _inconclusive('no price or total is shown on the page')
            return
        if one == two:
            _rule_broken(R, f"the amounts stayed {one[:4]} with 1 and with 2")
        # one more = one more unit price: total(2) - total(1) equals a price shown (the unit price, also with fees)
        follows = any(abs((y - x) - u) < 0.01 for x in one for y in two for u in one if u > 0)
        if not follows:
            _rule_broken(R, f"the amounts went {one[:4]} -> {two[:4]}: none grew by a unit price")
        _step_ok(f"the total follows '{R['a_name']}': {one[:3]} -> {two[:3]}")
        assert follows
        return
    elif rule == 'dependency':
        states = []
        for r in R.get('radios') or []:
            try:
                page.locator(r).first.check()
            except Exception:
                continue
            page.wait_for_timeout(300)
            states.append(page.locator(R['a']).first.is_enabled())
        if not states or len(set(states)) < 2:
            _rule_broken(R, f"the box stayed {'enabled' if states and states[0] else 'disabled'} for every choice")
        _step_ok(f"a choice enables '{R['a_name']}' and another disables it")
        assert len(set(states)) == 2
        return
    for o in R.get('others') or []:  # (the form's other required boxes get valid values: only the pair is wrong)
        try:
            if o.get('tick'):
                page.locator(o['selector']).first.check()
            else:
                _set(page, o['selector'], o['value'])
        except Exception:
            pass  # (a box that can't be filled: the rule is still tried, and _refused names what was refused)
    before, start = _go(page, R)
    ok, how = _refused(page, R, before, start, tried[n:])
    if not ok:
        _rule_broken(R, how)
    _step_ok(f"refused: {how}")
    assert ok
'''


def rules_script(cases: list[dict], header: list[str]) -> str:
    out = ['"""Rules between fields (common conventions): an end date before its start, the same city twice, min above',
           'max, a confirm box that differs, a count that must change the total, a choice that enables a box.',
           'A broken rule is a QUESTION ("[rule] ... Is that allowed?"), reported as a rule violation."""',
           *header, RULE_HELPERS, ""]
    for c in cases:
        s = c["spec"]
        guard = s["guard"]
        out += (["@pytest.mark.guest  # a public page: tested as a visitor"] if c.get("guest") else []) + [
            f"def test_{c['id']}(page{', write_guard' if guard else ''}):",
            f'    """{c["title"].replace(chr(34), chr(39)).replace(chr(92), "/")}"""',
            f"    R = {pformat(s, width=100, sort_dicts=False)}".replace("\n", "\n        "),
            f"    _check_rule(page, R{', write_guard' if guard else ''})", "", ""]
    return "\n".join(out).rstrip() + "\n"


def ai_suggestions(pages: list[dict]) -> list[dict]:
    """The AI may SUGGEST rules between boxes (only ids that exist; the rule engine decides). [] without an AI."""
    from .llm import LLMError, ask_structured, llm_enabled
    if not llm_enabled():
        return []
    forms = [{"page": p["url"], "boxes": [{"id": b.get("id") or b.get("name"), "label": _name(b), "type": b.get("type")}
                                         for b in g["boxes"] if b.get("id") or b.get("name")]}
             for p in pages for g in _groups(p)][:8]
    if not forms:
        return []
    known = {b["id"] for f in forms for b in f["boxes"]}
    try:
        got = ask_structured("Which pairs of boxes in these forms must follow a rule between them? Answer with rules "
                             f"from {list(RULES)} and the two box ids. Forms: {forms}", list[FieldRule],
                             agent="test_design", page="site")
    except (LLMError, ValueError, TypeError):
        return []
    return [{"rule": r.rule, "fields": r.fields[:2]} for r in got or [] if r.rule in RULES
            and r.fields and all(x in known for x in r.fields[:2])]
