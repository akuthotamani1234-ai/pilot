"""Test values that FIT each input box - like a tester who reads the label first.

field_kind(box) decides what the box is for, in this order: autocomplete -> type -> label / placeholder / name / id ->
inputmode (a placeholder "1234 5678 9012 3456" is a card number, "MM/YY" an expiry date). values(box) then gives
values with what the website should do with them:
  accept   a valid value: the form must take it          (e.g. the card 4111 1111 1111 1111 - it passes the Luhn check)
  reject   a wrong value: the form must refuse it        (e.g. a card number that fails the Luhn check, 13/30)
  either   a value with no universal rule (0 as an amount): its behaviour is only RECORDED, never a failure
plus boundaries from the box itself (maxlength, min, max, required).
"""
import re

KINDS = ("email", "password", "card_number", "card_expiry", "cvv", "phone", "zip", "url", "names", "age", "quantity",
         "amount", "number", "search", "date", "city", "text")

AUTOCOMPLETE = {"email": "email", "username": "text", "current-password": "password", "new-password": "password",
                "cc-number": "card_number", "cc-exp": "card_expiry", "cc-exp-month": "number", "cc-exp-year": "number",
                "cc-csc": "cvv", "tel": "phone", "tel-national": "phone", "postal-code": "zip", "url": "url",
                "name": "names", "given-name": "names", "family-name": "names", "additional-name": "names",
                "bday": "date", "address-level2": "city", "transaction-amount": "amount"}
TYPES = {"email": "email", "password": "password", "tel": "phone", "url": "url", "date": "date",
         "datetime-local": "date", "month": "date", "week": "date", "search": "search"}
WORDS = [  # (the first that matches the box's label / placeholder / name / id)
    ("card_expiry", r"expir|exp\.? ?date|valid (thru|until)|mm ?/ ?yy"),
    ("cvv", r"\b(cvv|cvc|csc|cvn|security code|card code)\b"),
    ("card_number", r"card ?(no|num|number)|cc-?num|credit ?card|debit ?card|\bpan\b"),
    ("email", r"e-?mail"),
    ("password", r"pass(word|code)|\bpwd\b"),
    ("phone", r"phone|mobile|\btel\b|contact (no|number)|whats ?app"),
    ("zip", r"\bzip\b|postal|post ?code|\bpin ?code\b"),
    ("url", r"website|\burl\b|homepage|link"),
    ("age", r"\bage\b|years old"),
    ("quantity", r"\bqty\b|quantity|how many|\bcount\b|number of"),
    ("amount", r"amount|price|\btotal\b|\bsum\b|budget|salary|\bfee\b|payment"),
    ("date", r"\bdate\b|\bdob\b|birth|depart|return|check-?in|check-?out|arrival"),
    ("city", r"\bcity\b|town|airport|origin|destination|\bfrom\b|\bto\b|location|station"),
    ("search", r"search|keyword|\bfind\b|\bquery\b"),
    ("names", r"\bname\b|first ?name|last ?name|surname|full ?name|nick ?name"),
]
CARD_PLACEHOLDER = re.compile(r"^\s*\d{4}([ -]?\d{4}){3}\s*$")
EXPIRY_PLACEHOLDER = re.compile(r"^\s*mm\s*/\s*yy(yy)?\s*$", re.I)


def _hint(box: dict) -> str:
    return " ".join(str(box.get(k) or "") for k in ("label", "placeholder", "name", "id", "accname")).lower()


def field_kind(box: dict) -> str:
    """What the box is for (one of KINDS); '' for boxes that take no typed value (checkbox, radio, file, select...)."""
    t = (box.get("type") or "").lower()
    if box.get("tag") == "select" or t in ("checkbox", "radio", "file", "submit", "button", "hidden", "image",
                                            "reset", "color", "range"):
        return ""
    ac = (box.get("autocomplete") or "").lower().split()
    ac = next((AUTOCOMPLETE[a] for a in ac if a in AUTOCOMPLETE), "")
    if ac and ac != "text":
        return ac
    if t in TYPES:
        return TYPES[t]
    ph = box.get("placeholder") or ""
    if CARD_PLACEHOLDER.match(ph):
        return "card_number"
    if EXPIRY_PLACEHOLDER.match(ph):
        return "card_expiry"
    hint = _hint(box)
    for kind, rx in WORDS:
        if re.search(rx, hint) and not (t == "number" and kind in ("names", "city", "search", "url")):
            return kind
    if t == "number" or (box.get("inputmode") or "") in ("numeric", "decimal"):
        return "number"
    return "text"


def luhn_ok(number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", number)]
    if len(digits) < 12:
        return False
    total = 0
    for n, d in enumerate(reversed(digits)):
        if n % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _v(value, expect: str, why: str) -> dict:
    return {"value": value, "expect": expect, "why": why}


BASE = {
    "email": [_v("qa.tester@example.com", "accept", "a valid e-mail"),
              _v("qa.tester", "reject", "no @ and no domain"), _v("a@", "reject", "no domain after the @")],
    "password": [_v("Qa-Test#2026x", "accept", "a strong password")],
    "card_number": [_v("4111 1111 1111 1111", "accept", "a test card number that passes the Luhn check"),
                    _v("4111 1111 1111 1112", "reject", "fails the Luhn check"),
                    _v("abcd efgh ijkl mnop", "reject", "letters instead of digits")],
    "card_expiry": [_v("12/30", "accept", "a future month"), _v("13/30", "reject", "there is no 13th month")],
    "cvv": [_v("123", "accept", "3 digits"), _v("12", "reject", "too short")],
    "phone": [_v("+1 555 010 0199", "accept", "an international phone number"),
              _v("phone", "reject", "letters instead of digits")],
    "zip": [_v("10001", "accept", "a postal code"), _v("!!!", "reject", "only symbols")],
    "url": [_v("https://example.com", "accept", "a valid web address"), _v("not a url", "reject", "not an address")],
    "names": [_v("QA Tester", "accept", "a person's name")],
    "age": [_v("30", "accept", "an adult age"), _v("-5", "reject", "a negative age"), _v("abc", "reject", "not a number")],
    "quantity": [_v("1", "accept", "one"), _v("-1", "reject", "a negative quantity"), _v("abc", "reject", "not a number"),
                 _v("0", "either", "zero: allowed by some forms")],
    "amount": [_v("100", "accept", "an amount"), _v("-1", "reject", "a negative amount"),
               _v("abc", "reject", "letters"), _v("0", "either", "zero: allowed by some forms")],
    "number": [_v("5", "accept", "a number"), _v("abc", "reject", "letters instead of a number")],
    "date": [_v("2030-06-15", "accept", "a date in the future")],
    "city": [_v("London", "accept", "a place")],
    "search": [_v("test", "accept", "a search word")],
    "text": [_v("QA test text", "accept", "ordinary text")],
}


def values(box: dict) -> list[dict]:
    """The values to try in this box, each with accept / reject / either - plus the box's own boundaries."""
    kind = field_kind(box)
    if not kind:
        return []
    out = [dict(v) for v in BASE[kind]]
    t = (box.get("type") or "").lower()
    if box.get("required"):
        out.append(_v("", "reject", "required, left empty"))
        if kind in ("names", "text", "email", "city", "phone", "zip", "url", "search"):  # (the browser's 'required'
            out.append(_v("   ", "reject", "only spaces: it looks filled in, but it is empty"))  # lets spaces through)
    ml = box.get("maxlength")
    if ml and kind in ("text", "names", "search", "city") and int(ml) < 500:
        out.append(_v("x" * int(ml), "accept", f"exactly the maximum length ({ml})"))
    lo, hi = box.get("min"), box.get("max")
    if t == "number" or kind in ("age", "quantity", "amount", "number"):
        try:
            if lo not in (None, ""):
                out = [v for v in out if not (v["expect"] == "accept" and float(v["value"] or 0) < float(lo))]
                out += [_v(str(_num(lo)), "accept", f"the minimum ({lo})"), _v(str(_num(lo) - 1), "reject", f"below the minimum ({lo})")]
            if hi not in (None, ""):
                out = [v for v in out if not (v["expect"] == "accept" and v["value"] and float(v["value"]) > float(hi))]
                out += [_v(str(_num(hi)), "accept", f"the maximum ({hi})"), _v(str(_num(hi) + 1), "reject", f"above the maximum ({hi})")]
        except ValueError:
            pass
        if not any(v["expect"] == "accept" for v in out):
            out.insert(0, _v(str(_num(lo or 1)), "accept", "a number in range"))
    if t == "number":  # (a number box can't hold letters: the browser keeps it empty - nothing to learn)
        out = [v for v in out if not re.search(r"[a-z]", v["value"] or "", re.I)]
    seen, uniq = set(), []
    for v in out:
        if v["value"] not in seen:
            seen.add(v["value"])
            uniq.append(v)
    return uniq


def _num(v) -> int:
    f = float(v)
    return int(f) if f.is_integer() else f


def valid_value(box: dict, tag: str = "") -> str:
    """A value the form should accept - names and texts carry the run's tag (qa-<run>-<n>) so the record can be found
    again and cleaned up."""
    kind = field_kind(box)
    if kind in ("names", "text") and tag:
        ml = int(box.get("maxlength") or 0)
        v = f"QA {tag}" if kind == "names" else f"QA test {tag}"
        return v[:ml] if ml else v
    if kind == "email" and tag:
        return f"{re.sub(r'[^a-z0-9.-]', '', tag.lower())}@example.com"
    accept = next((v["value"] for v in values(box) if v["expect"] == "accept"), "")
    return accept
