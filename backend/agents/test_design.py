"""Agent 2 — Test Design Agent.

Reads the application map and decides WHAT should be tested - every test case has ONE purpose and its own result:
  checks     one focused test case per feature / control of a page (search, a form's validation, a dropdown, a menu,
             login with a wrong password ...) - a failing check never fails another one; a control shared by many
             pages (the header's search box or menu) is tested once
  features   one test case per feature with a rule about its result (sorting, filters, pages, quantity, wishlist)
  learned    what each control did while exploring, done again
  journeys   real end-to-end workflows (log in, search -> product -> cart, fill a form, the menu): separate tests
  small      the site-wide checks (every page opens, no JavaScript errors, pictures, links, input values)
  blocked    protected actions, never performed
With an LLM: the model adds journeys of its own (AI flows).
"""
import json
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from ..actions import PROTECTED, action_class as classify_action
from ..ai_grounding import account_permission_reason
from ..auth import login_form  # (the login form finder lives with the login logic; re-used here)
from ..config import settings
from ..excel import _ident, write_workbook
from ..features import shown_first
from ..llm import LLMError, ask_structured, llm_enabled, load_prompt
from ..navigation import opener_path
from ..observe import READING_SUBMIT  # (a search / filter form's button: it only reads)
from ..page_status import page_testable
from ..state import QAState
from ..testdata import field_kind, values as fitting_values

SYSTEM = (
    "You are a senior QA engineer. You design precise, executable UI test cases for web pages. "
    "You never design destructive tests (deleting data, payments, logging out, sending real emails)."
)

# Buttons we never click automatically: every consequential action (pay, order, delete, send, save, submit,
# change password, log out ...) - see backend/actions.py. They are reported as Blocked (needs approval).
UNSAFE_BUTTON = PROTECTED
# Forms that are never submitted, not even empty for the validation check (the empty-form check expects the
# website to refuse it; these would cost money or delete data if it didn't)
FORM_UNSAFE = re.compile(
    r"delete|remove|log ?out|sign ?out|\bpay\b|buy|purchase|check ?out|place order|order now|"
    r"unsubscribe|deactivate|cancel (account|subscription|order)|transfer|send money|confirm", re.I)


def safe_buttons(p: dict) -> list[dict]:
    """Buttons on this page that are safe to click (form submit buttons are tested by the form tests). A button whose
    effect was learned while exploring gets a test of that effect instead (learned_cases) - and a button that only
    appears after another one is opened can't be clicked on a freshly opened page."""
    learned = {b.get("selector") for b in p.get("behaviour", []) if b.get("effect") not in ("error", None)}
    out = []
    for b in p.get("buttons", []):
        text = (b.get("text") or "").strip()
        if not b.get("first_seen", True):        # already tested on an earlier page (header/footer)
            continue
        if b.get("selector") in learned or b.get("revealed_by"):
            continue
        if (b.get("type") or "").lower() == "submit" and b.get("in_form", True):
            continue  # a form's submit button is tested by the form tests
        if b.get("disabled") or b.get("inert"):
            continue  # can't be clicked by a person either
        if not text and not b.get("selector"):
            continue
        # Prefer action_class (role/nav context) so "Pay Grades" menu links are not treated as payment.
        if classify_action(text, b.get("selector"), role=b.get("role"), kind=b.get("kind"),
                           tag=b.get("tag")) in ("pay", "delete", "logout", "password", "write"):
            continue
        if UNSAFE_BUTTON.search(text) or UNSAFE_BUTTON.search(b.get("selector") or ""):
            continue
        out.append(b)
    return out


def lean(items):
    """Elements without their raw HTML (kept for the code-fix report, not needed by the AI -> fewer tokens)."""
    if isinstance(items, list):
        return [lean(x) for x in items]
    if isinstance(items, dict):
        return {k: lean(v) for k, v in items.items() if k not in ("html", "open_tag", "data_first", "first_seen")}
    return items


def _box_name(i: dict) -> str:
    """How a person calls an input box: its label, placeholder or name (never a CSS selector)."""
    name = (i.get("label") or i.get("placeholder") or i.get("name") or i.get("id") or "input").strip()
    name = re.sub(r"\s+", " ", name).rstrip(":*").strip()
    return name[:40] or "input"


# ---------------------------------------------------------------- features on the page (search, cart, quantity)

ADD_TO_CART = re.compile(r"\badd\b.{0,12}\b(cart|basket|bag|trolley)\b", re.I)
# quantity buttons: "+" / "-" or a name such as "Increase quantity" (often only in aria-label)
PLUS = re.compile(r"^\s*(\+|＋)\s*$|\b(increment|increase|plus|qty up)\b", re.I)
MINUS = re.compile(r"^\s*(-|–|−|－)\s*$|\b(decrement|decrease|minus|qty down)\b", re.I)


def _first_word(names: list[str]) -> str:
    """A real word from the items listed on the page, to search for (e.g. 'Brocolli - 1 Kg' -> 'Brocolli')."""
    for n in names:
        for w in re.findall(r"[A-Za-z]{4,}", n):
            return w
    return ""


MONEY_TEXT = re.compile(r"[₹$€£]|\b(rs|inr|usd|eur)\.?\s?\d", re.I)
CALL_TO_ACTION = re.compile(r"^\s*(view|see|show|open|read|shop|buy|add|more|details|learn|quick)\b", re.I)


def _card_names(il: dict) -> list[str]:
    """The name on each item card: its first line that is no price and no button ('Rs. 500 / Blue Top / Add to cart'
    -> 'Blue Top')."""
    out = []
    for card in il.get("cards") or []:
        name = next((t.strip() for t in card.split("\n") if len(t.strip()) >= 3 and re.search("[A-Za-z]{3}", t)
                     and not MONEY_TEXT.search(t) and not CALL_TO_ACTION.search(t) and not ADD_TO_CART.search(t)), "")
        if name:
            out.append(name)
    return out


def _item_names(p: dict) -> list[str]:
    """The names of the items the page lists: its product cards and the elements that say they are an item's name -
    never its headings ('Welcome', 'Home' are no product to search for). When every card's link says the same
    ('View Product' x 34 on automationexercise.com), that is a button, not a name: the cards' own names are used
    ('Product' was searched for, and the shopping journey looked for an item named 'View'). (An app map of an older
    version: its item names.)"""
    il = p.get("itemLinks") or {}
    links = [(l.get("text") or "").strip() for l in il.get("links") or []]
    said = {t.casefold() for t in links if t}
    generic = len(links) >= 2 and len(said) == 1
    cards = (_card_names(il) or links) if generic or not said else links
    named = p["productNames"] if "productNames" in p else (p.get("itemNames") or [])
    named = [n for n in named if not (generic and (n or "").strip().casefold() in said)]
    return [n.strip() for n in dict.fromkeys(cards + list(named)) if n and n.strip()]


SEARCH_STOP = {"with", "from", "your", "this", "that", "pack", "free", "sale", "best", "more", "only", "items",
               "item", "home", "shop", "view", "details", "price", "cart", "size", "color", "colour", "edition",
               "product", "products"}


def site_search_word(pages: list[dict]) -> str:
    """The word the search tests look for: a word of a real item name of THIS website (from its listed items), in a
    few items - 2 or 3 if possible, so the results can be checked - not in all of them. '' = no items are listed.
    (An item listed twice - 'ABSOLUE EYE CREAM' on one page, 'Absolue Eye Cream' on another - is one item: a word of
    only one item may make the shop open that item's page instead of a list of results.)"""
    names, words, seen = [], [], set()
    for n in (n for p in pages for n in _item_names(p)):
        if n.casefold() not in seen:
            seen.add(n.casefold())
            names.append(n)
    for w in (w for n in names for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", n)):
        if w.lower() not in SEARCH_STOP and ("w", w.casefold()) not in seen:
            seen.add(("w", w.casefold()))
            words.append(w)
    if not words:
        return ""
    hits = {w: sum(1 for n in names if w.lower() in n.lower()) for w in words}
    most = max(3, len(names) // 4)
    return min(words, key=lambda w: (not 2 <= hits[w] <= most, abs(hits[w] - 2), words.index(w)))


def _section(url: str) -> str:
    return urlparse(url).path.strip("/").split("/")[0].lower()


def section_search_word(p: dict, pages: list[dict], word: str) -> str:
    """The word THIS page's search box looks for. The site's item word, when the page's own section lists items with
    it (the catalog); else a word of the titles of the section's own item pages (a blog: its posts - their links all
    say 'View post'). A product word typed into the blog's search finds nothing, and that is no bug."""
    mine = [q for q in pages if _section(q["url"]) == _section(p["url"])]
    if not word or any(word.lower() in n.lower() for q in mine for n in _item_names(q)):
        return word
    hrefs = {(l.get("href") or "").rstrip("/") for q in mine for l in (q.get("itemLinks") or {}).get("links") or []}
    titles = [q["headings"][0] for q in pages if q.get("headings") and q["url"].rstrip("/") in hrefs]
    return site_search_word([{"itemLinks": {"links": [{"text": t} for t in titles]}}]) or word


def site_item_pages(pages: list[dict]) -> list[str]:
    """The address patterns of the website's item pages, as exploring found them ('/product/{id}',
    '/index.php?rt=product/product&{id}'): a search may open the page of its only match instead of a results list."""
    from .discovery import _pattern
    out = []
    for p in pages:
        key = _pattern(p["url"], False) if p.get("page_type") == "product" else None
        if key and "{id}" in key[1]:
            out.append(key[1])
    return sorted(set(out))


def features(p: dict) -> dict:
    """Which everyday features this page has, and how to reach them. Empty values = not on this page."""
    p = shown_first(p)
    def btn(rx):  # by its text, or by the name a screen reader announces ("+" = "Increase quantity")
        return next((b for b in p.get("buttons", []) if b.get("selector") and not b.get("disabled")
                     and (rx.search((b.get("text") or "").strip()) or rx.search((b.get("accname") or "").strip()))
                     and not UNSAFE_BUTTON.search(b.get("text") or "")), None)
    search = next((i for i in p.get("inputs", []) if i.get("selector") and (
        (i.get("type") or "").lower() == "search"
        or "search" in f"{i.get('placeholder')} {i.get('name')} {i.get('id')} {i.get('label')}".lower())), None)
    add, plus, minus = btn(ADD_TO_CART), btn(PLUS), btn(MINUS)
    qty = next((i for i in p.get("inputs", []) if i.get("selector") and (i.get("type") or "").lower() == "number"), None)
    # the list of items on the page (product cards...): a control repeated many times, e.g. "ADD TO CART" x 30
    many = [b for b in p.get("buttons", []) if (b.get("count") or 1) > 1 and b.get("selector")]
    repeated = add if add and add in many else max(many, key=lambda b: b["count"], default=None)
    return {
        "search": search["selector"] if search else "", "search_name": _box_name(search) if search else "",
        # (the site's search word - set by the test design for every page - else a word of this page's items)
        "word": (p["site_word"] if "site_word" in p else _first_word(_item_names(p))) if search else "",
        # the addresses of the website's item lists (a search result page may show only 1 or 2 of its cards)
        "site_cards": list(p.get("site_cards") or []),
        "item_pages": list(p.get("site_items") or []),  # (the address patterns of its item pages)
        "cards": (p.get("itemLinks") or {}).get("selector") or "",  # the listed items (their cards hold name + price)
        "items": repeated["selector"] if repeated else "", "item_count": repeated["count"] if repeated else 0,
        "add": add["selector"] if add else "", "add_text": (add.get("text") or "").strip() if add else "",
        "qty": qty["selector"] if qty and plus and minus else "",
        "plus": plus["selector"] if plus and qty else "", "minus": minus["selector"] if minus and qty else "",
    }


def feature_cases(p: dict) -> list[dict]:
    """Does each feature actually WORK? (not only 'it can be clicked'). Checkout / pay / buy are never touched."""
    f, page, out = features(p), _page_name(p), []
    if f["search"] and f["word"]:  # (the word of a real item of this website - test_design_agent picks it)
        out.append({"id": "search_finds_item", "title": f"Search finds '{f['word']}'", "type": "positive",
                    "priority": "high", "test_data": f["word"], "verification": "business",
                    "feature_kind": "search",
                    "steps": [f"Open {page}", f"Type '{f['word']}' into the '{f['search_name']}' box", "Press Enter",
                              "Read the list of results (the item cards - not the menus)"],
                    "expected": f"The results list items named with '{f['word']}'; a result without it in its name "
                                "mentions it on its own page (description, tags)"})
    if f["search"]:
        out.append({"id": "search_no_results", "title": "Search for something that doesn't exist", "type": "negative",
                    "priority": "medium", "test_data": "zzqx-no-such-item", "verification": "business",
                    "feature_kind": "search",
                    "steps": [f"Open {page}", f"Type 'zzqx-no-such-item' into the '{f['search_name']}' box", "Press Enter"],
                    "expected": "No items are listed, or the page says nothing was found; no JavaScript error"})
    if f["add"]:
        out.append({"id": "add_to_cart", "title": f"'{f['add_text']}' adds the item", "type": "positive",
                    "priority": "high", "test_data": "",
                    "steps": [f"Open {page}", f"Click the first '{f['add_text']}' button"],
                    "expected": "The page reacts: the button or the cart shows the item was added; no errors"})
    if f["qty"]:
        out.append({"id": "quantity_plus_minus", "title": "Quantity + and − buttons change the number",
                    "type": "positive", "priority": "medium", "test_data": "",
                    "steps": [f"Open {page}", "Note the quantity of the first item", "Click +", "Click −"],
                    "expected": "+ raises the quantity by 1, − lowers it back by 1"})
    return out + control_cases(p)


def control_cases(p: dict) -> list[dict]:
    """One check per control any page can have: every dropdown, radio group, checkbox, and every box or
    control that opens something (calendar, list, passengers panel, suggestions while typing)."""
    p = shown_first(p)
    page, out, used = _page_name(p), [], set()

    def key(prefix: str, name: str) -> str:
        base = f"{prefix}_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')[:30] or 'item'}"
        k, n = base, 1
        while k in used:
            n += 1
            k = f"{base}_{n}"
        used.add(k)
        return k

    inputs = [i for i in p.get("inputs", []) if i.get("selector") and not i.get("disabled") and i.get("data_first", True)
              and not _line_box(p, i)]  # (not a box of one cart line: see LINE_FIELD)
    kind_of = lambda i: (i.get("type") or "").lower()  # noqa: E731
    # "JS Confirm" only opens a confirm box - "Confirm Order" is an action (protected): never clicked
    dialog_safe = lambda b: b.get("kind") == "dialog" and (  # noqa: E731
        re.fullmatch(r"\s*((js |click for js )?(alert|confirm|prompt)( box)?)\s*", b.get("text") or "", re.I)
        or not UNSAFE_BUTTON.search(b.get("text") or ""))

    for i in [i for i in inputs if i.get("tag") == "select" and len(i.get("options") or []) >= 2][:6]:
        name, opts = _box_name(i), i["options"]
        shown = ", ".join(o["text"] for o in opts[:6]) + (" …" if len(opts) > 6 else "")
        out.append({"id": key("dropdown", name), "kind": "dropdown", "type": "positive", "priority": "medium",
                    "title": f"'{name}' dropdown: every option can be chosen", "test_data": shown,
                    "steps": [f"Open {page}", f"Choose each option in the '{name}' dropdown: {shown}"],
                    "expected": "Each chosen option is shown as selected; no errors",
                    "selector": i["selector"], "options": [o["value"] for o in opts[:10]]})

    groups: dict[str, list] = {}
    for i in inputs:
        if kind_of(i) == "radio":
            groups.setdefault(i.get("name") or i["selector"], []).append(i)
    for g in [g for g in groups.values() if len(g) >= 2][:4]:
        labels = [_box_name(r) for r in g[:8]]
        names = " / ".join(labels)
        out.append({"id": key("choice", labels[0]), "kind": "radio", "type": "positive", "priority": "medium",
                    "title": f"Choices {names}: each one can be picked, only one at a time", "test_data": names,
                    "steps": [f"Open {page}"] + [f"Pick '{l}'" for l in labels],
                    "expected": "The picked choice is selected and the others are not",
                    "radios": [r["selector"] for r in g[:8]]})

    for i in [i for i in inputs if kind_of(i) == "checkbox"][:8]:
        name = _box_name(i)
        out.append({"id": key("checkbox", name), "kind": "checkbox", "type": "positive", "priority": "low",
                    "title": f"'{name}' checkbox can be ticked and unticked", "test_data": "",
                    "steps": [f"Open {page}", f"Tick '{name}'", f"Untick '{name}'"],
                    "expected": "It shows ticked after the first click and unticked after the second",
                    "selector": i["selector"]})

    controls = [b for b in p.get("buttons", []) if b.get("selector") and b.get("first_seen", True)
                and not b.get("disabled") and (not UNSAFE_BUTTON.search(b.get("text") or "") or dialog_safe(b))]
    label = lambda b: (b.get("text") or "control").split("\n")[0].strip()[:40] or "control"  # noqa: E731
    # what each control did while exploring: its test then checks THAT (the panel's text, the dialog's message), not
    # only "something changed"
    beh = {b.get("selector"): b for b in p.get("behaviour", []) if b.get("effect") not in ("error", None)}
    seen = lambda sel: [a for a in ((beh.get(sel) or {}).get("added") or [])  # noqa: E731
                        if 2 < len(a) < 120 and not a.startswith("[shadow] ")][:2]  # (a component's text: test_learned)

    tabs = [b for b in controls if b.get("kind") == "tab"][:8]
    if len(tabs) >= 2:
        names = " / ".join(label(b) for b in tabs)
        out.append({"id": key("tabs", label(tabs[0])), "kind": "tabs", "type": "positive", "priority": "medium",
                    "title": f"Tabs {names}: each one opens its own content", "test_data": names,
                    "steps": [f"Open {page}"] + [f"Click the '{label(b)}' tab" for b in tabs],
                    "expected": "Each clicked tab becomes the active one and shows its content",
                    "tabs": [b["selector"] for b in tabs], "seen": {b["selector"]: seen(b["selector"]) for b in tabs}})
    for b in [b for b in controls if b.get("kind") == "modal"][:4]:
        out.append({"id": key("popup", label(b)), "kind": "modal", "type": "positive", "priority": "medium",
                    "title": f"'{label(b)}' opens a popup that can be closed", "test_data": "",
                    "steps": [f"Open {page}", f"Click '{label(b)}'", "Close the popup"],
                    "expected": "A popup opens, and it closes again with Esc or its Close button",
                    "selector": b["selector"]})
    for b in [b for b in controls if b.get("kind") == "dialog"][:4]:
        out.append({"id": key("alert", label(b)), "kind": "dialog", "type": "positive", "priority": "medium",
                    "title": f"'{label(b)}' shows its alert / confirm box", "test_data": "",
                    "steps": [f"Open {page}", f"Click '{label(b)}'", "Press OK (a question box: answer 'QA Tester')"],
                    "expected": "The browser's box appears" + (f", saying what it said while exploring "
                                                               f"('{(beh.get(b['selector']) or {}).get('message', '')[:60]}')"
                                                               if (beh.get(b["selector"]) or {}).get("message") else ""),
                    "selector": b["selector"], "said": (beh.get(b["selector"]) or {}).get("message") or ""})
    for b in [b for b in controls if b.get("kind") == "sort"][:6]:  # (a bug often hides in the 4th column: Score)
        out.append({"id": key("sort", label(b)), "kind": "sort", "type": "positive", "priority": "medium",
                    "title": f"Clicking the '{label(b)}' column sorts the table", "test_data": "",
                    "verification": "business", "feature_kind": "sort",
                    "steps": [f"Open {page}", f"Click the '{label(b)}' column header", "Click it again"],
                    "expected": "The column is in order after the first click (numbers as numbers, dates as dates) "
                                "and in the opposite order after the second", "selector": b["selector"]})
    for t in [t for t in p.get("tables") or [] if t.get("selector")][:2]:
        if t.get("search") and t.get("rows", 0) >= 2:
            out.append({"id": key("table_search", t["selector"]), "kind": "table_search", "type": "positive",
                        "priority": "high", "title": "Searching the table shows only the rows that match",
                        "test_data": "a word from the table, the same in UPPER case, a word that is nowhere",
                        "verification": "business", "feature_kind": "table_search",
                        "steps": [f"Open {page}", "Type a word taken from the table into its search box",
                                  "Type it in UPPER case", "Type a word that is nowhere", "Clear the box"],
                        "expected": "Every row shown contains the word; UPPER case shows the same rows; the nonsense "
                                    "word shows none; clearing shows every row again",
                        "selector": t["search"], "table": t["selector"]})
        if t.get("page_size") and len(t.get("sizes") or []) >= 2:
            out.append({"id": key("page_size", t["selector"]), "kind": "page_size", "type": "positive",
                        "priority": "medium", "title": f"Rows per page ({', '.join(t['sizes'])}) limits the table",
                        "test_data": ", ".join(t["sizes"]),
                        "verification": "business", "feature_kind": "page_size",
                        "steps": [f"Open {page}", f"Choose each number of rows: {', '.join(t['sizes'])}"],
                        "expected": "The table shows at most that many rows each time",
                        "selector": t["page_size"], "table": t["selector"], "sizes": t["sizes"]})
    for l in [l for l in p.get("links", []) if l.get("download") and not l.get("external")][:3]:
        path = urlparse(l["href"]).path
        ext = (re.search(r"\.(\w{2,5})$", path) or [None, ""])[1]
        name = (l.get("text") or path.rsplit("/", 1)[-1] or "file").strip()[:40]
        out.append({"id": key("download", name), "kind": "download", "type": "positive", "priority": "medium",
                    "title": f"'{name}' downloads its file", "test_data": "",
                    "steps": [f"Open {page}", f"Click '{name}'"],
                    "expected": "A file is downloaded without an error" + (f" (a .{ext} file)" if ext else ""),
                    "selector": f'a[download][href$="{path}"]' if path else "a[download]", "ext": ext})
    from ..items import pager_next
    nxt = pager_next(controls, label)
    if nxt:
        out.append({"id": key("next_page", label(nxt)), "kind": "next", "type": "positive", "priority": "medium",
                    "title": f"'{label(nxt)}' shows the next page of results", "test_data": "",
                    "steps": [f"Open {page}", f"Click '{label(nxt)}'"],
                    "expected": "Other items / rows are shown", "selector": nxt["selector"],
                    "seen": seen(nxt["selector"])})

    for i in [i for i in inputs if kind_of(i) == "range"][:3]:
        name = _box_name(i)
        out.append({"id": key("slider", name), "kind": "slider", "type": "positive", "priority": "low",
                    "title": f"'{name}' slider can be moved", "test_data": "lowest and highest value",
                    "steps": [f"Open {page}", f"Move the '{name}' slider to the lowest, then the highest value"],
                    "expected": "The slider's value follows", "selector": i["selector"]})
    for i in [i for i in inputs if kind_of(i) == "file"][:3]:
        name = _box_name(i)
        out.append({"id": key("upload", name), "kind": "upload", "type": "positive", "priority": "medium",
                    "title": f"'{name}' accepts a file", "test_data": "agentic-qa-test.txt (small text file)",
                    "steps": [f"Open {page}", f"Choose a small text file in '{name}' (it is not sent)"],
                    "expected": "The file is accepted by the box", "selector": i["selector"]})
    drags, drops = p.get("draggables") or [], p.get("droppables") or []
    src = next((d for d in drags if d.get("selector")), None)
    dst = next((d for d in drops if d.get("selector") and src and d["selector"] != src["selector"]), None) \
        or next((d for d in drags[1:] if d.get("selector") and src and d["selector"] != src["selector"]), None)
    if src and dst:
        out.append({"id": key("drag", label(src)), "kind": "drag", "type": "positive", "priority": "medium",
                    "title": f"'{label(src)}' can be dragged onto '{label(dst)}'", "test_data": "",
                    "steps": [f"Open {page}", f"Drag '{label(src)}' onto '{label(dst)}'"],
                    "expected": "The item moves (the page changes)", "selector": src["selector"], "target": dst["selector"]})
    for h in [h for h in p.get("hovers") or [] if h.get("selector")][:4]:
        name = (h.get("name") or label(h))[:40]  # (its steady words: the cart menu '2 ITEMS - $59.00' -> 'ITEMS')
        out.append({"id": key("hover", name), "kind": "hover", "type": "positive", "priority": "low",
                    "title": f"Pointing at (or clicking) '{name}' shows its menu / details", "test_data": "",
                    "steps": [f"Open {page}", f"Move the mouse over '{name}' - a menu that opens on a click: click it"],
                    "expected": "Its sub-menu or details appear", "selector": h["selector"],
                    "seen": seen(h["selector"])})

    lf = login_form(p)  # login form: a wrong password must be rejected; the test account must work
    if lf:
        base = {"type": "negative", "priority": "high", **lf}
        out.append(dict(base, id=key("login_wrong_password", "form"), kind="login_wrong",
                        title="Login with a wrong password is rejected", test_data="agentic-qa-test / wrong-password-123",
                        steps=[f"Open {page}", "Type 'agentic-qa-test' as the user name",
                               "Type 'wrong-password-123' as the password", "Click the login button"],
                        expected="You are not logged in; the login form or an error message is still shown"))
        if settings.test_username and settings.test_password:
            out.append(dict(base, id=key("login_works", "form"), kind="login_ok", type="positive",
                            title="Login with the test account works", test_data="the test account",
                            steps=[f"Open {page}", "Type the test account's user name and password", "Click the login button"],
                            expected="You are logged in: the login form is gone or another page opens"))

    openers = [("box", i) for i in inputs if i.get("opener") and i.get("tag") != "select"
               and kind_of(i) in ("text", "search", "")]
    # a control that only LOOKS like an opener by its name ('Select this flight') and did nothing while exploring:
    # no "it opens" claim - its learned test asks for some response, and a failure there is a question (suspect)
    did_nothing = {b.get("selector") for b in p.get("behaviour", []) if b.get("effect") == "nothing"}
    openers += [("control", b) for b in controls if b.get("opener") and b.get("tag") != "a" and not b.get("kind")
                and b["selector"] not in did_nothing]
    openers += [("control", b) for b in controls if b.get("kind") == "collapse"]
    for what, el in openers[:8]:
        name = _box_name(el) if what == "box" else ((el.get("text") or "control").split("\n")[0].strip()[:40])
        typing = bool(el.get("suggests"))
        what_opens = ("shows suggestions while typing" if typing
                      else "opens its pictures / viewer" if re.search(r"gallery|photo|image|picture|zoom|video|preview", name, re.I)
                      else "opens its hidden part" if el.get("kind") == "collapse"
                      else "opens its list / calendar" if what == "box" else "opens its list / panel")
        out.append({"id": key("opens", name), "kind": "opens", "type": "positive", "priority": "medium",
                    "title": f"'{name}' {what_opens}",
                    "test_data": "a few letters" if typing else "",
                    "steps": [f"Open {page}", f"Type a few letters into the '{name}' box" if typing
                              else f"Click the '{name}' {'box' if what == 'box' else 'control'}"],
                    "expected": "A list of suggestions appears" if typing else "A list, calendar or panel opens",
                    "selector": el["selector"], "typing": typing})
    return out


# ---------------------------------------------------------------- coverage: what was found, what gets tested

# Honesty note for coverage.json / UI: selector-in-script ≠ a business oracle passed.
COVERAGE_SCRIPTED_NOTE = (
    "Observed/scripted controls are not the same as business-verified checks. "
    "'tested' means a generated script uses the control's selector — not that a product rule was proven."
)


def coverage(p: dict, code: str) -> dict:
    """Every control found on the page, marked tested / not tested (with the reason), so nothing is skipped silently.
    A control counts as tested when a generated test really uses it (its selector is in the test code).
    Status values stay Excel/UI-compatible (tested / not tested); optional `meaning` clarifies scripted reach."""
    def in_code(s: str | None) -> bool:
        return bool(s) and (repr(s) in code or s in code)

    used = {s for s in [b.get("selector") for b in p.get("buttons", [])] + [i.get("selector") for i in p.get("inputs", [])]
            + [x.get("selector") for x in (p.get("hovers") or []) + (p.get("draggables") or [])] if in_code(s)}
    f = features(p)
    if in_code(f["search"]):  # the search tests press Enter instead of its search button
        used.update(b["selector"] for b in p.get("buttons", []) if b.get("selector")
                    and "search" in f"{b.get('text')} {b['selector']}".lower())

    items = []

    def add(name, kind, el, earlier):
        s = el.get("selector")
        meaning = None
        if s and s in used:
            status, why, meaning = "tested", "", "scripted"
        elif earlier:
            status, why, meaning = "tested", "same as on an earlier page - tested there", "scripted"
        elif UNSAFE_BUTTON.search(name or "") or (s and UNSAFE_BUTTON.search(s)):
            status, why = "not tested", "not used on purpose: it could buy, pay, delete or log out"
        elif el.get("disabled") or el.get("inert"):
            status, why = "not tested", "disabled on the page (a person can't use it either)"
        elif not s:
            status, why = "not tested", "could not be located reliably on the page"
        elif (el.get("type") or "").lower() == "submit" and el.get("in_form", True):
            status, why = "not tested", "form submit button: the form is not sent (to avoid creating real data)"
        else:
            status, why = "not tested", "no automatic test for this kind of control yet"
        row = {"name": (name or "?").split("\n")[0][:60], "kind": kind, "status": status, "reason": why,
               "frame": el.get("frame", ""), "shadow": " > ".join(el.get("shadow_path") or []), "selector": s}
        if meaning:
            row["meaning"] = meaning
        items.append(row)

    for b in p.get("buttons", []):
        kind = {"tab": "tab", "modal": "popup button", "collapse": "show / hide section", "dialog": "alert button",
                "sort": "table column", "next": "next page"}.get(b.get("kind"), "custom control" if b.get("custom") else "button")
        add(b.get("text") or "button", kind + (f" (x{b['count']})" if (b.get("count") or 1) > 1 else ""), b,
            not b.get("first_seen", True))
    seen_inputs = set()
    for i in p.get("inputs", []):
        if i.get("selector") in seen_inputs:
            continue  # the same box repeated (e.g. one quantity box per product)
        seen_inputs.add(i.get("selector"))
        t = "dropdown" if i.get("tag") == "select" else (i.get("type") or "text")
        add(_box_name(i), {"radio": "choice", "range": "slider", "file": "file upload"}.get(t, f"{t} box"), i,
            not i.get("data_first", True))
    for h in p.get("hovers") or []:
        add(h.get("text"), "hover menu", h, False)
    for d in p.get("draggables") or []:
        add(d.get("text"), "draggable item", d, False)
    links = [l for l in p.get("links", []) if l.get("href", "").startswith("http")]
    if links:
        items.append({"name": f"{len(links)} links", "kind": "links", "status": "tested",
                      "reason": "each one is opened by the link test", "meaning": "scripted"})
    # embedded frames: a same-site frame's controls are listed above (with their frame); other frames say why not
    for fr in p.get("frames") or []:
        if fr.get("status") == "testable":
            items.append({"name": str(fr.get("name"))[:60], "kind": "embedded frame (iframe)", "status": "tested",
                          "reason": f"its {fr.get('buttons', 0)} control(s) and {fr.get('inputs', 0)} box(es) are listed "
                                    "with this frame", "frame": " > ".join(fr.get("path") or []),
                          "meaning": "scripted"})
        else:
            items.append({"name": str(fr.get("name") or fr.get("url"))[:60], "kind": "embedded frame (iframe)",
                          "status": "not tested", "reason": fr.get("reason") or fr.get("status"),
                          "frame": " > ".join(fr.get("path") or [])})
    if not p.get("frames"):  # (a page read before frames were inventoried)
        for fr in p.get("iframes") or []:
            items.append({"name": str(fr)[:60], "kind": "embedded frame (iframe)", "status": "not tested",
                          "reason": "its content was not read"})
    for u in p.get("unsupported") or []:  # a closed shadow root: nothing inside can be read - said, never guessed
        items.append({"name": u.get("tag") or "web component", "kind": "web component", "status": "not tested",
                      "reason": u.get("reason") or "unsupported", "frame": u.get("frame", ""),
                      "shadow": " > ".join(u.get("shadow_path") or [])})
    tested = sum(1 for x in items if x["status"] == "tested")
    return {"page": p.get("slug"), "url": p.get("url"), "tested": tested, "total": len(items), "items": items,
            "notes": [COVERAGE_SCRIPTED_NOTE]}


def _page_name(p: dict) -> str:
    return f"the '{p['title']}' page" if p.get("title") else f"the page {p['url']}"


def rule_based_cases(p: dict) -> list[dict]:
    """Test cases that make sense for any page — used when no LLM is configured. Steps in plain English."""
    p = shown_first(p)
    page = _page_name(p)
    cases = [
        {"id": "page_loads", "title": "Page loads successfully", "type": "smoke", "priority": "high",
         "steps": [f"Open {page}"], "expected": "The page opens without an error and has a title"},
        {"id": "no_console_errors", "title": "No JavaScript errors on the page", "type": "smoke",
         "priority": "medium", "steps": [f"Open {page}", "Wait until it has finished loading"],
         "expected": "The browser reports no JavaScript errors"},
    ]
    # (every LINK of the whole site is tested once in test_all_links.py - see script_generator)
    cases += feature_cases(p)  # search / add to cart / quantity: does the feature really work?
    btns = safe_buttons(p)
    if btns:
        names = ", ".join(f"'{(b.get('text') or '').split(chr(10))[0].strip() or 'button'}'" for b in btns[:6])
        cases.append({"id": "buttons_click", "title": f"Every button can be clicked without errors ({len(btns)} button(s))",
                      "type": "positive", "priority": "medium",
                      "steps": [f"Open {page}", f"Click each button: {names}{' …' if len(btns) > 6 else ''}"],
                      "expected": "No JavaScript errors and no error page after any click"})
    if p.get("imageCount"):
        cases.append({"id": "images_load", "title": "All images load", "type": "smoke", "priority": "low",
                      "steps": [f"Open {page}", "Look at every picture on the page"], "expected": "No broken images"})
    for f in p.get("forms", []):
        if f.get("submit") and FORM_UNSAFE.search(f["submit"].get("text") or ""):
            continue  # never submit a "Pay" / "Delete" / "Transfer" form, even empty
        if settings.environment == "production":
            continue  # production: no form is ever submitted (it could create real records)
        # (also a filter form of an app: OrangeHRM's 'Username / User Role / Status' with its button 'Search' - sent
        # empty it lists every record, which is right)
        searchy = READING_SUBMIT.match((f.get("submit") or {}).get("text") or "") or any(
            (fl.get("type") or "") == "search" or re.search(
                r"\b(q|query|search|keywords?)\b", f"{fl.get('name')} {fl.get('label')} {fl.get('placeholder')}", re.I)
            for fl in f["fields"])
        if searchy and not any(fl.get("required") for fl in f["fields"]):
            continue  # a search / filter form is not a data form: "send it empty" just shows all items
        submit = ((f.get("submit") or {}).get("text") or "Submit").strip() or "Submit"
        # forms with required fields, or real data forms (2+ fields, e.g. register) - not a 1-box search form.
        # Only a box you type in can be left empty: a list always has a choice ('Add to cart' with its quantity list)
        fillable = [fl for fl in f["fields"] if fl["type"] not in ("checkbox", "radio")
                    and not (fl["type"] or "").startswith("select")]
        if f.get("submit") and (any(fl.get("required") for fl in fillable)):
            boxes = ", ".join(f"'{_box_name(fl)}'" for fl in fillable[:5])
            cases.append({"id": f"form{f['index']}_required_validation",
                          "title": f"Form {f['index'] + 1}: submitting it empty is rejected",
                          "type": "negative", "priority": "high",
                          "steps": [f"Open {page}", f"Leave the boxes empty: {boxes}", f"Click the '{submit}' button"],
                          "expected": "The form is not sent and an error message is shown"})
        email = next((fl for fl in f["fields"] if fl["type"] == "email"), None)
        if email and f.get("submit"):
            cases.append({"id": f"form{f['index']}_invalid_email",
                          "title": f"Form {f['index'] + 1}: invalid email is rejected",
                          "type": "negative", "priority": "high", "test_data": "not-an-email",
                          "steps": [f"Open {page}", f"Type 'not-an-email' into the '{_box_name(email)}' box",
                                    f"Click the '{submit}' button"],
                          "expected": "The email box is marked invalid and the form is not sent"})
    return cases


# ---------------------------------------------------------------- test data: many values per input box

DATA_TYPES = {"text", "search", "email", "password", "tel", "url", "number", "textarea", ""}
EXPECT_TEXT = {
    "valid": "The box accepts it (no error shown)",
    "invalid": "The box rejects it (marked invalid / not kept)",
    # a box that only SAYS it is an e-mail / quantity box (type "text"): the browser does not check it, only the website
    # can - when the form is sent, which the tests never do. Without a visible error it is not known: inconclusive.
    "invalid?": "The box marks it invalid; if it shows nothing, the website's own check is not known (the form is "
                "never sent): inconclusive, not a defect",
    "robust": "The page keeps working: no JavaScript error, no popup, nothing breaks",
    "xss": "Shown as plain text only: the script does NOT run (no popup)",
}


def _show(value: str) -> str:
    """How a test value is written in Excel (so empty / spaces / long values are readable)."""
    if value == "":
        return "(empty)"
    if not value.strip():
        return f"(only {len(value)} spaces)"
    if len(value) > 60 and len(set(value)) == 1:
        return f'{len(value)} × "{value[0]}"'
    return value


def _sample(i: dict, t: str) -> str:
    """A normal, valid value for this box, guessed from its name."""
    hint = f"{i.get('label')} {i.get('name')} {i.get('placeholder')} {i.get('id')}".lower()
    if t == "search" or "search" in hint:
        v = "Login"
    elif "user" in hint:
        v = "ravi_kumar"
    elif "first" in hint:
        v = "Ravi"
    elif "last" in hint or "surname" in hint:
        v = "Kumar"
    elif "name" in hint:
        v = "Ravi Kumar"
    elif "city" in hint:
        v = "Hyderabad"
    elif "zip" in hint or "pin" in hint or "postal" in hint:
        v = "500001"
    elif "age" in hint:
        v = "30"
    elif t == "textarea" or "message" in hint or "comment" in hint:
        v = "This is a test message."
    else:
        v = "Hello test"
    mn, mx = i.get("minlength") or 0, i.get("maxlength") or 0
    if mn and len(v) < mn:
        v += "x" * (mn - len(v))
    if mx and len(v) > mx:
        v = v[:mx]
    return v


def hinted_type(i: dict) -> str | None:
    """A plain text box whose label says what it really is (e.g. 'Email' but type="text") -> that type."""
    if (i.get("type") or "text").lower() not in ("text", "") or i.get("tag") == "textarea":
        return None
    hint = f"{i.get('label')} {i.get('name')} {i.get('placeholder')} {i.get('id')}".lower()
    if re.search(r"e-?mail", hint):
        return "email"
    if re.search(r"\b(website|url|homepage|web site)\b", hint):
        return "url"
    if re.search(r"\b(age|quantity|qty|amount)\b", hint) and not re.search(r"phone|mobile", hint):
        return "number"
    return None


def _variants(i: dict) -> list[tuple[str, str, str, str]]:
    """(variant id, value, what it tests, expectation) for one input box."""
    t = "textarea" if i.get("tag") == "textarea" else (i.get("type") or "text").lower()
    t = hinted_type(i) or t   # an 'Email' text box is checked like an email box (it should reject bad emails)
    req, mn, mx = bool(i.get("required")), i.get("minlength") or 0, i.get("maxlength") or 0
    pattern = bool(i.get("pattern"))
    ok = "robust" if pattern else "valid"   # a pattern may legitimately refuse our sample, so don't demand "valid"
    v = []
    if t == "email":
        v += [("valid", "test.user@example.com", "a normal email address", ok),
              ("no_at", "testuser.example.com", "an email without @", "invalid"),
              ("no_domain", "testuser@", "an email with nothing after @", "invalid"),
              ("no_name", "@example.com", "an email with nothing before @", "invalid"),
              ("double_at", "test@@example.com", "an email with two @ signs", "invalid"),
              ("space", "test user@example.com", "an email with a space inside", "invalid")]
    elif t == "url":
        v += [("valid", "https://example.com", "a normal web address", ok),
              ("not_url", "not a website", "text that is not a web address", "invalid"),
              ("no_scheme", "www.example.com", "an address without https://", "invalid")]
    elif t == "number":
        lo, hi = _num(i.get("min")), _num(i.get("max"))  # the box's own limits (min="1" max="10")
        good = int((lo + hi) // 2) if lo is not None and hi is not None else \
            max(int(lo), 42) if lo is not None else min(int(hi), 42) if hi is not None else 42
        v += [("valid", str(good), "a normal number" + (" (inside its limits)" if lo is not None or hi is not None
                                                          else ""), ok),
              ("letters", "abc", "letters in a number box", "invalid"),
              ("negative", "-5", "a negative number", "robust"),
              ("decimal", "3.75", "a decimal number", "robust"),
              ("huge", "99999999999999999999", "a very large number", "robust")]
        if lo is not None:  # boundaries: the smallest allowed number is accepted, one less is refused
            v += [("at_min", f"{lo:g}", f"the smallest allowed number ({lo:g})", "valid"),
                  ("below_min", f"{lo - 1:g}", f"one less than the smallest allowed ({lo:g})", "invalid")]
        if hi is not None:
            v += [("at_max", f"{hi:g}", f"the largest allowed number ({hi:g})", "valid"),
                  ("above_max", f"{hi + 1:g}", f"one more than the largest allowed ({hi:g})", "invalid")]
    elif t == "tel":
        v += [("valid", "+91 98765 43210", "a normal phone number", ok),
              ("letters", "abcdefghij", "letters in a phone box", "robust"),
              ("short", "123", "a too-short phone number", "robust")]
    elif t == "password":
        v += [("valid", "Passw0rd!2024", "a normal strong password", ok),
              ("short", "abc", "a very short password", "invalid" if mn > 3 else "robust"),
              ("spaces", "        ", "a password of only spaces", "robust"),
              ("unicode", "Pässwörd123", "a password with accented letters", "robust")]
    elif field_kind(i) in ("card_number", "card_expiry", "cvv", "amount", "zip", "age", "quantity"):
        # a box for a card number, an expiry date, an amount ... (from its label / placeholder): values that FIT it
        # (backend/testdata.py). A plain text box is not checked by the browser: a wrong value it keeps is only a
        # question (inconclusive) - unless its pattern lets the browser check it
        for n, x in enumerate(fitting_values(i)):
            exp = {"accept": ok, "reject": "invalid" if pattern else "invalid?", "either": "robust"}[x["expect"]]
            v.append((f"{field_kind(i)}_{n}", x["value"], f"{x['why']} ('{x['value']}')", exp))
    else:  # text, search, textarea
        v += [("valid", _sample(i, t), "a normal value", ok),
              ("numbers", "12345", "only numbers", "robust"),
              ("symbols", "ravi@#$%&*!", "special characters", "robust"),
              ("unicode", "Jöhn राम 名前", "other languages (accents, Hindi, Japanese)", "robust"),
              ("emoji", "😀👍🔥", "emoji", "robust"),
              ("spaces", "     ", "only spaces", "robust"),
              ("trim", "  ravi  ", "spaces before and after", "robust")]
    v.append(("empty", "", "leaving it empty" + (" (it is required)" if req else ""), "invalid" if req else "valid"))
    if mn > 1:
        v.append(("too_short", "a" * (mn - 1), f"one character less than the minimum ({mn})", "invalid"))
    if mx:
        v.append(("max_exact", "a" * mx, f"exactly the maximum length ({mx})", "valid" if t not in ("email", "url", "number") else "robust"))
        v.append(("max_plus_1", "a" * (mx + 1), f"one character more than the maximum ({mx})", f"max:{mx}"))
    if t != "number":
        v += [("sql", "' OR '1'='1' --", "a database attack text (SQL injection)", "robust"),
              ("script", "<script>alert('xss')</script>", "a script attack text (XSS)", "xss"),
              ("very_long", "a" * 500, "a very long value (500 characters)", f"max:{mx}" if mx else "robust")]
    return v


def mark_first_seen_inputs(app_map: list[dict]) -> None:
    """A box that appears on many pages (e.g. the header search) gets its test data only on the first page."""
    seen = set()
    for p in app_map:
        for i in p.get("inputs", []):
            key = (_box_name(i).lower(), (i.get("type") or "").lower(), i.get("selector"))
            i["data_first"] = key not in seen
            seen.add(key)


def _num(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


# a box of ONE LINE of the cart (quantity[1:] on the cart / checkout page): it is only there while the cart holds that
# item - a fresh test browser has none. The cart is tested by the quantity test and the journey (they add the item).
# (On a product page the same kind of name is the product's own option: option[350] - that one is tested.)
LINE_FIELD = re.compile(r"\w\[[^\]]+\]")


def _line_box(p: dict, i: dict) -> bool:
    return p.get("page_type") in ("cart", "checkout") and bool(LINE_FIELD.search(i.get("name") or ""))


# The cart page's OWN boxes, choices and forms (coupon, shipping estimate, quantities, update) are only there while the
# cart holds an item - every test starts in a fresh browser with an empty cart, so they get no test of their own there.
CART_STATE = ("only shown while the cart holds an item - a test starts with an empty cart, so it has no test of its "
              "own (the shopping journey tests the cart: its line, quantity, price and total)")


def data_cases(p: dict) -> list[dict]:
    """One test case per (input box, test value). Values are typed and checked; the form is never submitted."""
    if not settings.data_tests or p.get("page_type") == "cart":  # (cart: see CART_STATE)
        return []
    p = shown_first(p)  # (a box that only appears after another control is opened: tested by the learned tests)
    page, out, used = _page_name(p), [], set()
    boxes = [i for i in p.get("inputs", []) if i.get("selector") and i.get("data_first", True) and not _line_box(p, i)
             and not i.get("readonly") and not i.get("disabled")  # can't be typed into (e.g. a date box)
             and not HONEYPOT.search(f"{i.get('label')} {i.get('name')} {i.get('id')} {i.get('placeholder')}")
             and (("textarea" if i.get("tag") == "textarea" else (i.get("type") or "text").lower()) in DATA_TYPES)]
    for i in boxes[:settings.data_max_fields]:
        name = _box_name(i)
        key = _ident(i.get("name") or i.get("id") or name)[:30]
        while key in used:
            key += "_2"
        used.add(key)
        for vid, value, what, expect in _variants(i):
            if expect == "invalid" and hinted_type(i):  # (a text box the browser does not check)
                expect = "invalid?"
            exp_text = (f"The box keeps at most {expect[4:]} characters" if expect.startswith("max:")
                        else EXPECT_TEXT[expect])
            out.append({
                "id": f"data_{key}_{vid}", "type": "data",
                "priority": "high" if expect in ("invalid", "xss") or vid == "sql" else "medium",
                "title": f"'{name}' box: {what}",
                "test_data": _show(value),
                "steps": [f"Open {page}", f"Click into the '{name}' box",
                          f"Type: {_show(value)}" if value else "Leave it empty", "Click outside the box"],
                "expected": exp_text,
                # used by the script generator and the code-fix report (not shown in Excel)
                "field": name, "selector": i["selector"], "value": value, "expect": expect,
                "suggest_type": hinted_type(i), "box_html": i.get("html") or "",
            })
    return out


# ---------------------------------------------------------------- plain-English safety net for AI-written steps

def humanize(cases: list[dict], p: dict) -> list[dict]:
    """Replace CSS selectors the AI wrote in steps / titles / expected results with the names people see."""
    names = {}
    for i in p.get("inputs", []):
        if i.get("selector"):
            names[i["selector"]] = f"the '{_box_name(i)}' box"
    for b in p.get("buttons", []):
        text = (b.get("text") or "").split("\n")[0].strip()
        if b.get("selector") and text:
            names[b["selector"]] = f"the '{text[:40]}' button"
    # leftover selectors: '#search-input' (id) or '[name="q"]' (attribute) - not "Form #1" or "[optional]"
    sel_re = re.compile(r"""(?:\s*using (?:the )?(?:selector|locator)\s*)?['"`]?(#[A-Za-z][\w-]*|\[[\w-]+[*^$|~]?=[^\]]*\])['"`]?""")

    def fix(text: str) -> str:
        if not isinstance(text, str):
            return text
        for sel, human in sorted(names.items(), key=lambda kv: -len(kv[0])):
            for q in ("'", '"', "`", ""):
                text = text.replace(f"using selector {q}{sel}{q}", "").replace(f"{q}{sel}{q}", human)
        # anything still looking like a selector (#id, .class, [attr]) -> drop the robot words around it
        text = sel_re.sub(" the element", text)
        return re.sub(r"\s{2,}", " ", text).replace(" ,", ",").strip()

    for c in cases:
        c["title"] = fix(c.get("title", ""))
        c["expected"] = fix(c.get("expected", ""))
        if isinstance(c.get("steps"), list):
            c["steps"] = [fix(s) for s in c["steps"]]
    return cases


# ---------------------------------------------------------------- focused checks: one feature / control per test case
# (They were bundled into one "large" case per page before: one failing step - e.g. a menu whose text had changed -
# failed the whole case, and every feature it touched was reported failed. Now each has its own result.)

LARGE = 20  # journeys / AI flows per run (each a long journey of 8-20 steps across pages) - the user asked for 20
#             large test cases + the 5 small site-wide checks per website; the one-feature checks stay as they are
NOT_STEPS = ("page_loads", "no_console_errors", "images_load")  # these run on every page in the small checks


def page_steps(p: dict) -> list[dict]:
    """Everything a person can do on one page (features, controls, forms, buttons) - each one a focused check."""
    return [c for c in rule_based_cases(p) if c["id"] not in NOT_STEPS]


def _short(p: dict) -> str:
    """A short page name: its title, or - when every page has the same title - its address ('dynamic controls')."""
    if p.get("_same_title") or not p.get("title"):
        return (p.get("slug") or "page").replace("_", " ").strip()[:40]
    return p["title"].split(" | ")[0].split(" – ")[0].split(" - ")[0].strip()[:40]


CHECK_FEATURE = {"search_finds_item": "Search", "search_no_results": "Search", "add_to_cart": "Add to cart",
                 "quantity_plus_minus": "Quantity", "buttons_click": "Buttons (click only)"}
KIND_FEATURE = {"dropdown": "Dropdown", "radio": "Choices (radio buttons)", "checkbox": "Checkbox", "tabs": "Tabs",
                "opens": "Opens a list / panel", "modal": "Popup", "dialog": "Alert box", "sort": "Table sorting",
                "next": "Pagination", "hover": "Menu", "drag": "Drag and drop", "slider": "Slider",
                "upload": "File upload", "login_wrong": "Login", "login_ok": "Login"}


def _check_feature(s: dict) -> str:
    if re.search(r"_(required_validation|invalid_email)$", s["id"]):
        return "Form validation"
    return CHECK_FEATURE.get(s["id"]) or KIND_FEATURE.get(s.get("kind"), "Page feature")


def _step_selectors(p: dict, s: dict) -> list[str]:
    """The elements a step uses (to know whether two pages' steps test the same thing)."""
    f, sid = features(p), s["id"]
    if sid.startswith("search_"):
        return [f["search"]]
    if sid == "add_to_cart":
        return [f["add"]]
    if sid == "quantity_plus_minus":
        return [f["qty"], f["plus"], f["minus"]]
    if sid == "buttons_click":
        return sorted(b.get("selector") or "" for b in safe_buttons(p))
    m = re.match(r"form(\d+)_", sid)
    if m:  # a form is known by its boxes and its button (its own address may be 'form >> nth=0': ANY page's first form)
        form = next((x for x in p.get("forms", []) if str(x.get("index")) == m.group(1)), {})
        own = {x.get("selector") for x in form.get("fields", [])} | {(form.get("submit") or {}).get("selector")}
        return sorted(own - {None, ""}) or [form.get("selector") or sid]
    return [x for x in [s.get("selector"), s.get("user")] + list(s.get("radios") or []) + list(s.get("tabs") or []) if x]


def builtin_checks(pages: list[dict]) -> list[dict]:
    """One FOCUSED test case per thing a person can do on a page (search, a form's validation, a dropdown, a choice,
    a menu, login with a wrong password ...): each one has its own result, so one failing check never fails another.
    A control on many pages (the header's search box or menu, a footer form) is tested once, on the first page."""
    from ..registry import page_pattern
    where: dict[str, set] = {}  # element -> the page patterns it is on
    for p in pages:
        for x in p.get("buttons", []) + p.get("inputs", []) + (p.get("hovers") or []) + p.get("forms", []):
            if x.get("selector"):
                where.setdefault(x["selector"], set()).add(page_pattern(p))
    titles = [p.get("title") for p in pages]
    out, seen = [], set()
    for p in pages:
        p_named = dict(p, _same_title=titles.count(p.get("title")) > 1)
        for s in page_steps(p):
            sels = _step_selectors(p, s)
            shared = bool(sels) and all(len(where.get(x, ())) > 1 for x in sels)
            what = re.sub(r"\d+", "#", s["id"]) if s["id"].startswith("form") else s.get("kind") or s["id"]
            key = (what, tuple(sels), None if shared else page_pattern(p))
            if key in seen or (p.get("page_type") == "cart" and sels and not shared):
                continue  # (tested already - or a control of the cart's own content: see CART_STATE)
            seen.add(key)
            n = len(out) + 1
            out.append({
                "id": f"check_{n}", "kind": "check", "type": s.get("type") or "positive",
                "priority": s.get("priority") or "medium",
                "title": f"{s['title']} ({_short(p_named)})", "test_data": str(s.get("test_data") or ""),
                "steps": list(s.get("steps") or []), "expected": s.get("expected") or "",
                "feature": _check_feature(s), "element": ", ".join(x for x in sels if x)[:120] or s["title"][:60],
                "page": p["slug"], "url": p["url"], "pages": [p["slug"]], "guest": not p.get("auth"),
                "parts": [{"page": p["slug"], "step": s}],  # (the registry links it to the feature its step checks)
                "files": ["test_checks.py"], "tests": [f"test_check_{n}"]})
    return out


# ---------------------------------------------------------------- real user journeys (built-in, also without AI)
# A journey is ONE test that keeps going like a person would - no page reload between its steps:
# log in and use the app, search -> add to cart -> open the cart, fill a whole form, click through the menu.

CART_WORDS = re.compile(r"cart|basket|bag|trolley", re.I)


def _cart_control(p: dict) -> dict | None:
    """The control that opens the cart / basket (never 'add to cart', checkout or buy)."""
    for b in p.get("buttons", []):
        t, s = (b.get("text") or "").strip(), b.get("selector") or ""
        if s and not b.get("disabled") and CART_WORDS.search(f"{t} {s}") and not ADD_TO_CART.search(t) \
                and not UNSAFE_BUTTON.search(t) and not re.search(r"\badd\b|proceed|check ?out", f"{t} {s}", re.I):
            return b
    return None


# Many shops show the cart icon only once something is in it, so the crawler (which never adds anything) can't see
# it: after 'Add to cart' the journey then clicks the cart control that has appeared (never an 'add' / checkout button).
CART_AFTER_ADD = {"selector": '[data-test*="cart" i]:not([data-test*="add" i]), '
                              '[data-testid*="cart" i]:not([data-testid*="add" i]), '
                              'a[href*="cart" i]:not([href*="add" i]), '
                              '[aria-label*="cart" i]:not([aria-label*="add" i]) >> visible=true',
                  "text": "the cart (its icon appears after adding)"}


def _cart_link(p: dict) -> dict | None:
    """A normal link to the cart page (<a href="/cart">Cart</a>) -> a control the tests can click."""
    from urllib.parse import urlparse
    for l in p.get("links", []):
        path = urlparse(l.get("href", "")).path
        if not l.get("external") and re.search(r"/(cart|basket|bag|trolley)/?$", path, re.I):
            return {"selector": f'a[href$="{path}"]', "text": (l.get("text") or "Cart").split("\n")[0].strip()[:30]}
    return None


def _number(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _value_for(i: dict) -> str | None:
    """A normal, valid value a person would type into this box (None = leave it, e.g. a date picker).

    Prefers field_kind / valid_value from testdata (labels + constraints); falls back for free text.
    """
    from ..testdata import field_kind, valid_value
    t = "textarea" if i.get("tag") == "textarea" else (i.get("type") or "text").lower()
    hint = " ".join(str(i.get(key) or "") for key in ("name", "id", "label", "placeholder", "autocomplete")).lower()
    if i.get("readonly") or i.get("disabled") or t in ("file", "range", "hidden", "submit", "button", "image", "color"):
        return None
    if field_kind(i) == "date" or re.search(r"\bdate\b|\bbirth|\bdob\b", hint) or t in ("date", "datetime-local", "time", "month"):
        from datetime import date, timedelta
        value = date(1995, 6, 15) if re.search(r"birth|dob|born", hint) else date.today() + timedelta(days=7)
        if t == "time":
            return "10:30"
        if t == "datetime-local":
            return value.isoformat() + "T10:30"
        if t == "month":
            return value.strftime("%Y-%m")
        if t == "date":
            return value.isoformat()
        placeholder = (i.get("placeholder") or "").lower()
        formats = {"yyyy-mm-dd": "%Y-%m-%d", "yyyy-dd-mm": "%Y-%d-%m", "dd/mm/yyyy": "%d/%m/%Y",
                   "mm/dd/yyyy": "%m/%d/%Y", "dd-mm-yyyy": "%d-%m-%Y", "mm-dd-yyyy": "%m-%d-%Y"}
        return value.strftime(formats[placeholder]) if placeholder in formats else None
    if t == "email" or re.search(r"e-?mail", hint):
        return "qa.tester@example.com"
    if t == "password":
        return "Passw0rd!2024"
    if t == "tel" or field_kind(i) == "phone":
        return "9876543210"
    if t == "number":  # (inside the box's own limits: 'Passengers' 1-9 gets 9, not 30)
        lo, hi = _number(i.get("min")), _number(i.get("max"))
        v = min(30.0, hi) if hi is not None else 30.0
        v = max(v, lo) if lo is not None else v
        return str(int(v)) if v.is_integer() else str(v)
    if t == "url" or re.search(r"website|url", hint):
        return "https://example.com"
    if t == "date":  # a birthday is in the past; a visit / booking / delivery date is in the future
        from datetime import date, timedelta
        return "1995-06-15" if re.search(r"birth|dob|born", hint) else (date.today() + timedelta(days=7)).isoformat()
    if t in ("text", "search", "textarea", ""):
        return valid_value(i) or _sample(i, t)
    return valid_value(i) or None


# an anti-spam trap: a box people never see or fill ("Leave this field blank") - robots that fill it are rejected
HONEYPOT = re.compile(r"leave (this )?(field |box )?(blank|empty)|do not (fill|enter|change)|don.t fill|honey ?pot|"
                      r"if you are (a )?human", re.I)


def _form_fields(p: dict, f: dict | None) -> list[dict]:
    """Every box / choice of a form, with the value a person would enter (the form is never sent)."""
    from collections import Counter

    from ..forms import keep_form_field
    from ..testdata import field_kind as kind_of
    counts = Counter(i.get("selector") for i in p.get("inputs", []))
    by_sel = {i.get("selector"): i for i in p.get("inputs", []) if counts[i.get("selector")] == 1}
    fields = f["fields"] if f else p.get("inputs", [])
    out, radio_groups = [], set()
    for x in fields:
        i = dict(by_sel.get(x.get("selector")) or {}, **x)
        if not keep_form_field(i):
            continue
        sel, t = i.get("selector"), (i.get("type") or "").lower()
        if not sel or t == "hidden" or i.get("global") or i.get("region") in ("navigation", "sidebar", "search") or HONEYPOT.search(
                f"{i.get('label')} {i.get('name')} {i.get('id')} {i.get('placeholder')}"):
            continue
        if i.get("tag") == "select" or t.startswith("select"):
            opts = i.get("options") or []
            if opts:
                out.append({"selector": sel, "kind": "select", "value": opts[0]["value"], "name": _box_name(i),
                            "shown": opts[0].get("text") or opts[0]["value"]})
            elif i.get("required"):
                out.append({"selector": sel, "kind": "unsupported", "name": _box_name(i), "shown": "no observed options"})
        elif t == "radio":
            group = i.get("name") or sel
            if group not in radio_groups:
                radio_groups.add(group)
                # (the choice the page already made - 'Round trip' - is the one a person keeps)
                made = next((r for r in fields if (by_sel.get(r.get("selector")) or r).get("checked")
                             and (by_sel.get(r.get("selector")) or r).get("name") == i.get("name")), None)
                if made and i.get("name"):
                    i, sel = by_sel.get(made.get("selector")) or made, made.get("selector")
                out.append({"selector": sel, "kind": "radio", "value": "", "name": _box_name(i), "shown": "picked",
                            "required": bool(i.get("required")), "label": i.get("label") or "",
                            "role": i.get("role") or "", "field_kind": ""})
        elif t == "checkbox":
            out.append({"selector": sel, "kind": "checkbox", "value": "", "name": _box_name(i), "shown": "ticked",
                        "required": bool(i.get("required")), "label": i.get("label") or "",
                        "role": i.get("role") or "", "field_kind": ""})
        else:
            v = _value_for(i)
            if v is not None:
                out.append({"selector": sel, "kind": "type", "value": v, "name": _box_name(i), "shown": v})
            elif i.get("required"):
                out.append({"selector": sel, "kind": "unsupported", "name": _box_name(i), "shown": "unsupported"})
        if out and out[-1].get("selector") == sel:
            out[-1].update(required=bool(i.get("required")), label=i.get("label") or "",
                           local_selector=i.get("local_selector"), role=i.get("role") or "", field_kind=kind_of(i), type=t)
    return out


def _journey(n: int, kind: str, title: str, steps: list[str], expected: str, pages: list[dict], spec: dict,
             guest: bool, test_data: str = "", priority: str = "high") -> dict:
    return {
        "id": f"journey_{n}", "kind": "journey", "journey": kind, "size": "large", "type": "end-to-end",
        "priority": priority, "title": title, "test_data": test_data, "steps": steps, "expected": expected,
        "page": ", ".join(dict.fromkeys(p["slug"] for p in pages)), "url": pages[0]["url"],
        "pages": list(dict.fromkeys(p["slug"] for p in pages)), "guest": guest, "spec": spec,
        "files": ["test_journeys.py"], "tests": [f"test_journey_{n}"],
    }


def builtin_journeys(pages: list[dict], limit: int = LARGE) -> list[dict]:
    """Real journeys built from what the crawler found (no AI needed). Checkout / pay / buy are never clicked."""
    from .discovery import _normalize
    out = []
    guests, users = [p for p in pages if not p.get("auth")], [p for p in pages if p.get("auth")]

    # 1) log in with the test account, then open the pages behind the login (the login must hold)
    lp = next((p for p in guests if login_form(p)), None)
    if lp and settings.test_username and settings.test_password:
        after = [{"url": p["url"], "name": _short(p)} for p in users[:8]]
        out.append(_journey(
            len(out) + 1, "login", f"Log in with the test account and use the app ({len(after)} page(s) behind the login)",
            [f"Open {_page_name(lp)}", "Type the test account's email / user name and password", "Click the login button",
             "You are logged in (the login form is gone)"] + [f"Open '{a['name']}' - you are still logged in" for a in after],
            "The login works and every page behind it opens without sending you back to the login page",
            [lp] + users[:8], dict(login_form(lp), url=lp["url"], after=after), guest=True, test_data="test account (TEST_USERNAME)"))

    # 2) shop: search an item -> add it to the cart -> open the cart -> the item is there (never checkout). The cart:
    # its button, or a normal link to the cart page (<a href="/basket">0 Basket</a> - a shop without item pages)
    for p in pages:
        f, cart = features(p), _cart_control(p) or _cart_link(p)
        if f["add"] and cart and len(out) < limit:
            word = f["word"]
            cart_name = (cart.get("text") or "cart").strip()[:30]
            out.append(_journey(
                len(out) + 1, "shop",
                f"Shop on '{_short(p)}': " + (f"search '{word}' → " if word else "") + "add to cart → open the cart"
                + (f" → '{word}' is in the cart" if word else ""),
                [f"Open {_page_name(p)}"] + ([f"Type '{word}' into the '{f['search_name']}' box and press Enter",
                                              f"'{word}' is shown"] if word else [])
                + [f"Click the first '{f['add_text']}' button", "The page shows the item was added",
                   f"Click '{cart_name}' to open the cart"]
                + ([f"'{word}' is listed in the cart"] if word else ["The cart opens and is not empty"])
                + ["Stop here - checkout / buy is never clicked"],
                "Searching finds the item, adding it updates the cart, and the cart shows it", [p],
                {"url": p["url"], "search": f["search"] if word else "", "word": word, "add": f["add"],
                 "add_text": f["add_text"], "cart": cart["selector"], "cart_text": cart_name,
                 "hints": list(p.get("site_cards") or []), "item_pages": list(p.get("site_items") or [])},
                guest=not p.get("auth"), test_data=word))

    # 2b) search -> open the first product -> choose an option -> add it to the cart -> the cart lists it
    from ..features import OPTION_HINT, page_features
    from .discovery import _parent_path, _pattern
    # the product page: one that a list's items OPEN first - a page that merely mentions 'Add to cart' is no product
    # (automationexercise.com's Test Cases page - 'Test Case 22: Add to cart from Recommended items' - was taken, no
    # list opens it, and the whole shopping journey was left out)
    opened = {_normalize(l.get("href", "")) for p in pages for l in (p.get("itemLinks") or {}).get("links") or []}
    products = [p for p in pages if p.get("page_type") == "product" and features(p)["add"]]
    prod = next((p for p in products if _normalize(p["url"]) in opened), products[0] if products else None)
    prod_pat = (_pattern(prod["url"], False) or (0, prod["url"], ()))[1:] if prod else None
    prod_folder = _parent_path(prod["url"]) if prod and not _pattern(prod["url"], False) else ""

    def opens_products(href: str) -> bool:  # same address pattern (/product/{id}) - or, for addresses without a
        return ((_pattern(href, False) or (0, None, ()))[1:] == prod_pat  # number (/products/red-oak-lamp), the
                or bool(prod_folder) and _parent_path(href) == prod_folder)  # same folder
    # the list whose items OPEN product pages
    lst = next((p for p in pages if p is not prod and any(
        opens_products(l.get("href", "")) for l in (p.get("itemLinks") or {}).get("links") or [])), None)
    cart = (_cart_control(prod) or _cart_link(prod) or CART_AFTER_ADD) if prod else None
    cart_page = next((c for c in pages if c.get("page_type") == "cart" and bool(c.get("auth")) == bool(
        (prod or {}).get("auth"))), None) or next((c for c in pages if c.get("page_type") == "cart"), None)
    if prod and lst and cart and len(out) < limit:
        pf, lf = features(prod), features(lst)
        word = lf["word"] if lf["search"] else ""
        options = [{"selector": i["selector"], "value": i["options"][-1]["value"], "name": _box_name(i)}
                   for i in prod.get("inputs", []) if i.get("tag") == "select" and len(i.get("options") or []) >= 2
                   and OPTION_HINT.search(f"{i.get('name')} {i.get('id')} {i.get('label')}")][:3]
        out.append(_journey(
            len(out) + 1, "product",
            f"Shopping journey: {'search a product → it is in the results → ' if word else ''}open it → "
            "add to cart → the cart lists it with its quantity"
            + (" → one more: the cart total goes up by its price" if settings.environment in ("test", "staging") else ""),
            [f"Open {_page_name(lst)}"] + ([f"Search for '{word}'", f"An item named with '{word}' is in the results"]
                                           if word else ["Read the list of items"])
            + ["Open that item", "Its page opens and shows its name"]
            + ["Choose a valid value for every option it needs (size, colour ...)"]
            + [f"Click '{pf['add_text']}'", "No error message appears", f"Open '{cart['text']}'",
               "The item is listed in the cart, with the price the list showed, and its quantity went up by one"]
            + (["Raise its quantity by one: the cart total goes up by exactly its price",
                "Remove the line this test added (cleanup) - it is gone"]
               if settings.environment in ("test", "staging") else [])
            + ["Stop here - checkout / pay is never clicked"],
            "Every step is verified: the right item is found, opened and added; the cart lists it with the right "
            "quantity and price; the total follows the quantity. A step that cannot be verified fails the journey.",
            [lst, prod] + ([cart_page] if cart_page else []),
            {"url": lst["url"], "search": lf["search"] if word else "", "word": word,
             "items": (lst.get("itemLinks") or {}).get("selector") or "",
             "hints": list(dict.fromkeys(x for x in [(lst.get("itemLinks") or {}).get("selector")]
                                         + list(lst.get("site_cards") or []) if x)),
             "item_pages": list(lst.get("site_items") or []),
             "options": options, "add": pf["add"],
             "add_text": pf["add_text"], "cart": cart["selector"], "cart_text": cart["text"],
             "cart_url": (cart_page or {}).get("url") or "", "guest": not prod.get("auth"),
             # in the cart: one more -> the total goes up by the price; then the line it added is removed again
             # (only on a test / staging environment: it changes the test account's cart)
             "change_cart": settings.environment in ("test", "staging")},
            guest=not prod.get("auth"), test_data=word))

    # 2c) orders: open an order from the list and see its details
    for p in pages:
        f = next((x for x in page_features(p) if x["kind"] == "order_link"), None)
        if f and len(out) < limit:
            # the order's own pages (/orders/1001/tracking): links on its details page that go one level deeper
            detail = next((d for d in pages if _normalize(d["url"]) == _normalize(f["href"])), None)
            base = urlparse(f["href"]).path.rstrip("/") + "/"
            subs = [{"href": l["href"], "text": (l.get("text") or "").split("\n")[0].strip()[:40]}
                    for l in (detail or {}).get("links", []) if not l.get("external")
                    and urlparse(l["href"]).path.startswith(base) and (l.get("text") or "").strip()][:3]
            out.append(_journey(
                len(out) + 1, "orders", f"Open an order from '{_short(p)}' and see its details"
                + (f" → {', '.join(s['text'] for s in subs)}" if subs else ""),
                [f"Open {_page_name(p)}", f"Click '{f['name'] or 'the first order'}'", "The order's details are shown"]
                + [f"Click '{s['text']}': its page opens (a page of this order)" for s in subs],
                "The order details page (and its own pages) open without an error and without logging out",
                [p] + [d for d in pages if d is detail or _normalize(d["url"]) in {_normalize(s["href"]) for s in subs}],
                {"url": p["url"], "href": f["href"], "name": f["name"], "subs": subs}, guest=not p.get("auth")))
            break

    # 3) fill every big form completely, like a person would (it is never sent)
    seen_forms = set()
    for p in pages:
        if p.get("page_type") == "cart":
            continue  # (its forms are only there while the cart holds an item: see CART_STATE)
        lf = login_form(p)
        forms = [f for f in p.get("forms", []) if not (lf and (f.get("submit") or {}).get("selector") == lf["submit"])]
        candidates = [(f, _form_fields(p, f)) for f in forms]
        for f, fields in candidates:
            key = tuple(sorted(x["name"] for x in fields))
            if len(fields) < 3 or key in seen_forms or len(out) >= limit:
                continue
            seen_forms.add(key)
            name = ((f or {}).get("submit") or {}).get("text") or _short(p)
            openers = opener_path(p, f["selector"], f.get("revealed_by")) if f else []
            required_fields = [{"selector": x["selector"], "name": x["name"], "kind": x.get("field_kind") or x["kind"]}
                               for x in fields if x.get("required")]
            j = _journey(
                len(out) + 1, "form", f"Fill the whole '{name.strip()[:30]}' form like a user ({len(fields)} boxes) - not sent",
                [f"Open {_page_name(p)}"]
                + [f"Open via '{step.get('name') or step['selector']}'" for step in openers]
                + [f"'{x['name']}': " + (f"type '{x['shown']}'" if x["kind"] == "type" else
                                         f"choose '{x['shown']}'" if x["kind"] == "select" else x["shown"])
                   for x in fields] + ["Do NOT send the form"],
                "Every box accepts a normal value - no box shows an error (interaction/input check only; "
                "not proof of Save, creation, update, search or persistence)", [p],
                {"url": p["url"], "form": (f or {}).get("selector") or "", "fields": fields,
                 "required_fields": required_fields, "openers": openers},
                guest=not p.get("auth"), test_data=", ".join(x["shown"] for x in fields if x["kind"] == "type")[:120])
            j["verification_level"] = "input_only"
            j["verification"] = "interaction"  # unsubmitted fill — no business-verified credit
            out.append(j)

    # 4) move through the website by clicking its menu like a person (visitor, and logged in)
    for group in (guests, users):
        if not group or len(out) >= limit:
            continue
        start = group[0]
        where = {_normalize(p["url"]): p for p in group}
        links, seen = [], set()
        for l in start.get("links", []):  # links to the other pages
            target = where.get(_normalize(l["href"]))
            text = (l.get("text") or "").split("\n")[0].strip()
            if not target or target is start or l.get("external") or not l.get("visible", True) or not text \
                    or target["url"] in seen:
                continue
            if UNSAFE_BUTTON.search(text):  # ('Checkout', 'Log out': never clicked - one of them must not block the
                continue                    # whole journey; the page itself is still checked by 'Every page opens')
            seen.add(target["url"])
            links.append({"text": text[:60], "href": l["href"], "to": target.get("final_url") or target["url"],
                          "name": _short(target)})
        # links to a part of a page (#projects - the menu of a one-page website): one click per section, menu first
        for s in sorted(start.get("sections", []), key=lambda s: not s.get("nav")):
            if not s.get("visible", True) or not s.get("text") or ("#" + s["section"]) in seen:
                continue
            seen.add("#" + s["section"])
            links.append({"text": s["text"][:60], "href": s["href"], "section": s["section"],
                          "to": s["href"].split("#")[0], "name": "#" + s["section"]})
        if len(links) >= 2:
            links = links[:12]
            out.append(_journey(
                len(out) + 1, "navigate",
                f"Move through the website by clicking its menu ({len(links)} links" + (", logged in)" if start.get("auth") else ")"),
                [f"Open {_page_name(start)}"] + [f"Click '{x['text']}' - " + (f"the page scrolls to its '{x['section']}' part"
                                                                              if x.get("section") else f"the '{x['name']}' page opens")
                                                 for x in links],
                "Every menu link opens the right page or part of the page, without errors"
                + (" and without logging you out" if start.get("auth") else ""),
                [start] + [p for p in (where.get(_normalize(x["href"])) for x in links) if p is not None],
                {"start": start["url"], "links": links, "logged_in": bool(start.get("auth"))},
                guest=not start.get("auth"), priority="medium"))
    return out[:limit]


def section_links(pages: list[dict]) -> list[dict]:
    """Links to a part of a page (#projects, /#contact) on the whole site - each must lead to a section that exists."""
    out, seen = [], set()
    for p in pages:
        for s in p.get("sections", []):
            target = s["href"].split("#")[0]
            key = (target.rstrip("/"), s["section"])
            if key in seen:
                continue
            seen.add(key)
            out.append({"page": target, "section": s["section"], "text": s.get("text") or "", "found_on": p["url"],
                        "guest": not p.get("auth")})
    return out


def small_checks(pages: list[dict], data: list[dict]) -> list[dict]:
    """The 5 small checks: each one runs on every page (or every link / every input box) of the site."""
    n_links = len({l["href"].split("#")[0] for p in pages for l in p.get("links", []) if l["href"].startswith("http")})
    n_sections = len(section_links(pages))
    boxes = len({c.get("field") for c in data})
    with_images = [p for p in pages if p.get("imageCount")]
    every = f"each of the {len(pages)} page(s)"
    data_files = sorted({f"test_{_ident(c['page'])}_data.py" for c in data})
    return [dict(c, size="small", page="all pages", url=pages[0]["url"]) for c in [
        {"id": "site_pages_open", "title": f"Every page opens ({len(pages)} pages)", "type": "smoke",
         "priority": "high", "steps": [f"Open {every}"], "expected": "Each page opens without an error and has a title",
         "files": ["test_site.py"], "tests": ["test_page_loads"]},
        {"id": "site_no_js_errors", "title": "No JavaScript errors on any page", "type": "smoke", "priority": "medium",
         "steps": [f"Open {every}", "Wait until it has finished loading"],
         "expected": "The browser reports no JavaScript errors", "files": ["test_site.py"], "tests": ["test_no_console_errors"]},
        {"id": "site_images", "title": f"All pictures load ({len(with_images)} page(s) with pictures)", "type": "smoke",
         "priority": "low", "steps": ["Open every page that has pictures", "Look at every picture"],
         "expected": "No broken pictures", "files": ["test_site.py"], "tests": ["test_images_load"],
         "skip_reason": "" if with_images else "The website has no pictures - nothing to check."},
        {"id": "site_links", "title": f"Every link works ({n_links} links"
                                      + (f", {n_sections} links to a part of a page)" if n_sections else ")"),
         "type": "smoke", "priority": "medium",
         "steps": ["Open every link found on the website (inside and outside it)"]
                  + (["For every link to a part of a page (like #projects): open that page, find that part"]
                     if n_sections else []),
         "expected": "No link leads to an error page, and every #section a link points to exists",
         "files": ["test_all_links.py"], "tests": ["test_link", "test_section_link"]},
        {"id": "site_input_values", "title": f"Input boxes handle wrong and unusual values ({len(data)} values, {boxes} boxes)",
         "type": "negative", "priority": "high", "verification": "interaction",
         "test_data": "empty, too long, numbers, symbols, other languages, emoji, attack text (SQL / script) …",
         "steps": ["Click into each input box", "Type each test value (it is only typed, the form is never sent)",
                   "Click outside the box"],
         "expected": "Valid values are accepted, invalid ones rejected, length limits kept, no script runs, nothing breaks "
                     "(interaction/input check only — not business-verified Save/persistence)",
         "files": data_files, "tests": ["test_data_*"], "checks": data},
    ]]


def _observed(p: dict) -> list[dict]:
    """What REALLY happened when exploring used the page's controls: what it did, what the website said (its own
    words - "alert: ..." = the browser's alert box), where it led. The AI's expected results come from this."""
    out = []
    for b in p.get("behaviour", []):
        if b.get("effect") in (None, "error"):
            continue
        seen = {"control": b["control"], "did": b["effect"], "said": (b.get("message") or "")[:120],
                "opens": urlparse(b.get("to") or "").path, "revealed": (b.get("revealed") or [])[:4]}
        out.append({k: v for k, v in seen.items() if v})
    return out[:15]


def _site_summary(pages: list[dict]) -> str:
    """What the AI needs to design the large test cases: every page, what is on it, what the built-in steps do, and
    what its controls did while exploring (observed)."""
    out = []
    from ..page_inventory import ai_component_summary
    for p in pages[:40]:  # (the app behind the login comes first in this list)
        out.append({
            "page": p["slug"], "url": p["url"], "title": p.get("title"), "logged_in": bool(p.get("auth")),
            "page_type": p.get("page_type"), "features": p.get("features") or [],
            "component_inventory": ai_component_summary(p),
            "headings": (p.get("headings") or [])[:5],
            "buttons": [{"text": (b.get("text") or "")[:40], "kind": b.get("kind"), "count": b.get("count")}
                        for b in p.get("buttons", [])[:20]],
            "inputs": [{"label": _box_name(i), "type": i.get("type"),
                        "options": [o["text"] for o in (i.get("options") or [])][:8]} for i in p.get("inputs", [])[:15]],
            "links": [l.get("text", "")[:30] for l in p.get("links", []) if not l.get("external")][:15],
            "items_listed": (p.get("itemNames") or [])[:6],
            "built_in_checks": [s["title"] for s in page_steps(p)][:12],
            "observed": _observed(p),
            **({"on_screen": on_screen(p)} if p.get("seen") else {}),
        })
    return json.dumps(out, indent=1)


def on_screen(p: dict) -> dict:
    """What the AI saw in the page's screenshot (backend/vision.py): its purpose, features and messages, word for word."""
    seen = p.get("seen") or {}
    return {"purpose": seen.get("purpose") or "",
            "features": [f"{f['name']} ({f['kind']}): {f.get('does') or ''}".strip()[:120]
                         for f in seen.get("features", [])[:25]],
            "messages": [m[:120] for m in seen.get("messages", [])[:10]]}


# What an AI test case talks about -> what a page of the site must really have. Small AI models (e.g. a 3B Ollama
# model) invent a search box or a cart for a site that has none: such a case would only give false failures.
def _has_box(p: dict, kind: str) -> bool:
    return any(i.get("tag") == kind or (i.get("type") or "") == kind for i in p.get("inputs", []))


def _mentions(p: dict, rx: str) -> bool:
    return any(re.search(rx, f"{x.get('text') or ''} {x.get('href') or ''}", re.I)
               for x in p.get("links", []) + p.get("buttons", []))


AI_NEEDS = [  # (words in the case, the thing it needs, does a page have it? (page, its feature kinds))
    (r"\bsearch", "a search box", lambda p, k: "search" in k),
    (r"\bcart\b|\bbasket\b", "a cart", lambda p, k: "add_to_cart" in k or bool(_cart_control(p))),
    (r"\bfilter", "filters", lambda p, k: "filter" in k),
    (r"\bsort", "sorting", lambda p, k: "sort" in k),
    (r"wish ?list", "a wishlist", lambda p, k: "wishlist" in k),
    (r"pagination|next page", "page links", lambda p, k: "pagination" in k),
    (r"drop-?down", "a dropdown", lambda p, k: _has_box(p, "select")),
    (r"check ?box", "a checkbox", lambda p, k: _has_box(p, "checkbox")),
    (r"\bradio", "radio buttons", lambda p, k: _has_box(p, "radio")),
    (r"check ?out", "a checkout", lambda p, k: _mentions(p, r"check ?out")),
    (r"forgot|reset (your |the )?password|password reset", "a password reset", lambda p, k: _mentions(p, r"forgot|reset")),
]


def _invented(case: dict, pages: list[dict], kinds: list[set]) -> str:
    """What the AI's test case needs but no page of the site has ('' = everything it uses is really there)."""
    from ..ai_grounding import invented_record_problem
    text = " ".join([str(case.get("title", "")), str(case.get("expected", "")), str(case.get("test_data", ""))]
                    + [str(s) for s in case.get("steps", [])])
    for rx, what, has in AI_NEEDS:
        if re.search(rx, text, re.I) and not any(has(p, k) for p, k in zip(pages, kinds)):
            return what
    # Invented demo people (John Doe, …) unless observed/seeded/required.
    people = invented_record_problem(text, pages, settings.requirements)
    if people:
        return people
    return ""


def _unsupported_expected_quote(expected: str, evidence: str) -> str:
    """Return an exact quoted expectation that appears in neither discovered evidence nor owner requirements."""
    if expected.strip().casefold().startswith("exploratory:"):
        return ""
    known = evidence.casefold()
    for match in re.finditer(r"\"([^\"]{3,120})\"|'([^']{3,120})'", expected):
        quoted = next((part for part in match.groups() if part is not None), "").strip()
        if quoted and quoted.casefold() not in known:
            return quoted
    return ""


class AICase(BaseModel):
    """One AI-designed test case - validated before it is used (structured output)."""
    title: str = Field(min_length=3, max_length=200)
    steps: list[str] = Field(min_length=2, max_length=25)  # (asked for 8-20: a long journey, one action per step)
    expected: str = Field(default="", max_length=600)
    priority: Literal["high", "medium", "low"] = "high"
    pages: list[str] = Field(default_factory=list)
    guest: bool = False
    test_data: str = ""

    @field_validator("test_data", mode="before")
    @classmethod
    def _data_as_text(cls, v):
        """The AI may write the data as fields ({'email': 'test@example.com', 'password': 'wrong'}): the same, as text."""
        if isinstance(v, dict):
            return ", ".join(f"{k}={x}" for k, x in v.items())
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return "" if v is None else v


class AILabel(BaseModel):
    """What the AI says a control's feature is - from the evidence of what it did (structured output)."""
    id: str
    feature: str = Field(min_length=2, max_length=60)
    category: Literal["navigation", "search", "filter", "sort", "pagination", "cart", "wishlist", "account", "form",
                      "content", "media", "help", "settings", "other"]
    expected: str = Field(min_length=3, max_length=200)


def ai_feature_labels(reg: dict) -> int:
    """ONE AI call for the whole site: name the feature of each control whose behaviour exploring learned, and say in
    plain words what a person should see - from the browser evidence only (unknown ids are dropped). The rule-based
    checks stay the judge; this only names things for people. Returns how many controls got a label."""
    learned = [f for f in reg["features"].values() if f["level"] == "control" and (f.get("evidence") or {}).get("effect")
               not in (None, "error")][:40]
    if not learned:
        return 0
    evidence = [{"id": f["id"], "control": f["name"], "role": f.get("role") or f["kind"], "page": f["pages"][0],
                 "did": {k: v for k, v in (f.get("evidence") or {}).items()
                         if k in ("effect", "message", "tone", "to", "revealed") and v}} for f in learned]
    labels = ask_structured(load_prompt("feature_labels").format(controls=json.dumps(evidence, indent=1)), list[AILabel],
                            system=SYSTEM, agent="test_design", page="features")
    known = {f["id"] for f in learned}
    for lab in labels:
        if lab.id in known:  # (an id the AI made up is ignored - grounded in the evidence only)
            reg["features"][lab.id].update(ai_feature=lab.feature, ai_category=lab.category, ai_expected=lab.expected)
    return sum(1 for lab in labels if lab.id in known)


def ai_flows(pages: list[dict]) -> list[dict]:
    """LARGE (20) large end-to-end test cases designed by the AI for the whole site (raises LLMError if it fails).
    The answer is validated (AICase) - a malformed one gets one corrective retry, then the rules are used."""
    by_slug = {p["slug"]: p for p in pages}
    wanted = settings.requirements.strip() or "(none given - design from what the website offers)"
    observed = (_site_summary(pages) + "\n" + settings.requirements).casefold()
    answer = [c.model_dump() for c in ask_structured(
        load_prompt("test_design").format(n=LARGE, site=_site_summary(pages), requirements=wanted[:4000]),
        list[AICase], system=SYSTEM, agent="test_design", page="site")]
    from ..features import page_features
    kinds = [{f["kind"] for f in page_features(p)} for p in pages]
    real = []
    for c in answer[:LARGE]:
        missing = _invented(c, pages, kinds)
        if missing:
            print(f"  [test-design] AI test case unsupported - {missing}: {str(c['title'])[:80]}")
            continue  # drop from executable suite — never product_defect
        real.append(c)
    out = []
    for n, c in enumerate(real, start=1):
        used = [s for s in (c.get("pages") or []) if s in by_slug] or [pages[0]["slug"]]
        steps = c["steps"] if isinstance(c["steps"], list) else [str(c["steps"])]
        # an outcome exploring never saw is not invented: the AI marks it "Exploratory:" (looked at, not judged)
        expected = str(c.get("expected") or "").strip()
        unsupported = _unsupported_expected_quote(expected, observed)
        if unsupported:
            print(f"  [test-design] exact expected text was not observed or required; marking exploratory: {unsupported[:80]}")
            expected = (f"Exploratory: the exact text '{unsupported}' was not observed or specified. Check the actual "
                        f"result against the owner's expected behavior. Original expectation: {expected}")[:600]
        guessed = expected.casefold().startswith("exploratory:")
        out.append({
            "id": f"ai_flow_{n}", "kind": "flow", "size": "large", "ai": True,
            "type": "exploratory" if guessed else "end-to-end",
            "priority": c.get("priority") if c.get("priority") in ("high", "medium", "low") else "high",
            "title": str(c["title"])[:150], "test_data": str(c.get("test_data") or ""),
            "steps": [str(s) for s in steps], "expected": expected,
            "page": ", ".join(used), "url": by_slug[used[0]]["url"], "pages": used,
            "guest": bool(c.get("guest")) or not any(by_slug[s].get("auth") for s in used),
            "files": ["test_flows_ai.py"], "tests": [f"test_ai_flow_{n}"],
            "verification": "interaction" if guessed else "business",
        })
    # Unsupported AI proposals were dropped above (logged). Never product_defect findings.
    for c in out:  # AI-written titles / steps in plain English (no CSS selectors)
        if c.get("kind") == "unsupported":
            continue
        why = account_permission_reason(c, allow_signup=settings.auto_register,
                                        has_account=bool(settings.test_username and settings.test_password)
                                                    or any(p.get("auth") for p in pages))
        if why:
            c.update(kind="blocked", blocked=True, ai=False, files=[], tests=[], skip_reason=why)
        humanize([c], by_slug[c["pages"][0]])
    return out


MY_TEST = "Your own test (plain English)"


def my_test_cases(pages: list[dict], tests: list[dict], start: int) -> list[dict]:
    """Your own tests in plain English (backend/my_tests.py) -> one test case each, written by the AI from what
    exploring found and scripted like its journeys (ai_flow_<start>...). A test the website can't do, or a run without
    an AI, stays in the list as not automated with the reason - never dropped."""
    if not tests or not pages:
        return []
    by_slug = {p["slug"]: p for p in pages}
    observed = _site_summary(pages).casefold()

    def kept(t: dict, why: str) -> dict:
        return {"id": f"my_test_{t['id']}", "kind": "mine", "size": "large", "type": "functional", "priority": "high",
                "title": t["text"][:150], "steps": [t["text"]], "expected": "-", "page": pages[0]["slug"],
                "url": pages[0]["url"], "pages": [pages[0]["slug"]], "requirement": MY_TEST, "my_test": t["id"],
                "feature": "Your own tests", "element": "as written by you", "files": [], "tests": [],
                "skip_reason": why}
    if not llm_enabled():
        return [kept(t, "Not automated: your own tests need an AI to turn them into steps - choose an AI in the chat")
                for t in tests]
    try:
        answer = ask_structured(load_prompt("my_tests").format(
            n=len(tests), site=_site_summary(pages), tests="\n".join(f"{n}. {t['text']}" for n, t in
                                                                   enumerate(tests, start=1))),
            list[AICase], system=SYSTEM, agent="test_design", page="my tests")
    except (LLMError, json.JSONDecodeError, ValueError) as e:
        print(f"  [test-design] your own tests: the AI failed ({str(e)[:120]}) - they stay as not automated")
        return [kept(t, f"Not automated: the AI could not turn it into steps this time ({str(e)[:80]})") for t in tests]
    from ..features import page_features
    kinds = [{f["kind"] for f in page_features(p)} for p in pages]
    out = []
    for i, t in enumerate(tests):
        c = answer[i].model_dump() if i < len(answer) else None
        if c is None:
            out.append(kept(t, "Not automated: the AI gave no steps for it"))
            continue
        if str(c.get("expected") or "").lower().startswith("not possible") or str(c["steps"][0]).lower().startswith(
                "not possible"):
            out.append(kept(t, f"Not automated: {str(c.get('expected') or c['steps'][-1])[:200]}"))
            continue
        missing = _invented(c, pages, kinds)
        if missing:
            out.append(kept(t, f"Not automated: the website has no {missing}"))
            continue
        n = start + len([x for x in out if x["kind"] == "flow"])
        used = [s for s in (c.get("pages") or []) if s in by_slug] or [pages[0]["slug"]]
        expected = str(c.get("expected") or "").strip()
        unsupported = _unsupported_expected_quote(expected, observed + "\n" + t["text"].casefold())
        if unsupported:
            print(f"  [test-design] exact expected text was not observed or requested; marking exploratory: {unsupported[:80]}")
            expected = (f"Exploratory: the exact text '{unsupported}' was not observed or requested. Check the actual "
                        f"result against the owner's expected behavior. Original expectation: {expected}")[:600]
        out.append({
            "id": f"ai_flow_{n}", "kind": "flow", "size": "large", "ai": True, "my_test": t["id"],
            "type": "exploratory" if expected.casefold().startswith("exploratory:") else "end-to-end",
            "priority": c.get("priority") if c.get("priority") in ("high", "medium", "low") else "high",
            "title": t["text"][:150], "test_data": str(c.get("test_data") or ""),
            "steps": [str(s) for s in c["steps"]], "expected": expected,
            "page": ", ".join(used), "url": by_slug[used[0]]["url"], "pages": used, "requirement": MY_TEST,
            "feature": "Your own tests", "element": "as written by you",
            "guest": bool(c.get("guest")) or not any(by_slug[s].get("auth") for s in used),
            "files": ["test_flows_ai.py"], "tests": [f"test_ai_flow_{n}"]})
        humanize([out[-1]], by_slug[used[0]])
        out[-1]["title"] = t["text"][:150]  # (your words stay the title)
    return out


# ---------------------------------------------------------------- structured test cases (every case has every field)

CASE_FIELDS = ("tc_id", "id", "title", "page", "url", "feature", "element", "type", "scenario", "priority", "risk",
               "preconditions", "test_data", "test_data_ref", "steps", "expected", "actual_result",
               "automation_status", "execution_status", "evidence", "requirement", "skip_reason")
LEVELS = ("high", "medium", "low")
SMALL_FEATURE = {"site_pages_open": ("Pages", "every page"), "site_no_js_errors": ("JavaScript", "every page"),
                 "site_images": ("Pictures", "every picture"), "site_links": ("Links", "every link"),
                 "site_input_values": ("Input boxes", "labels, placeholders, validation of every box")}
JOURNEY_FEATURE = {"login": ("Login", "login form"), "shop": ("Search + cart", "search box, add-to-cart, cart"),
                   "form": ("Form", "every box of the form"), "navigate": ("Navigation", "menu links"),
                   "product": ("Shopping journey", "item list, product page, options, add to cart, cart"),
                   "orders": ("Orders", "order list, order details")}
FEATURE_NAME = {"filter": "Filters", "sort": "Sorting", "pagination": "Pagination", "wishlist": "Wishlist",
                "search": "Search"}


def _stable_id(c: dict) -> str:
    """The same test case gets the same ID in every run (so runs can be compared): made from WHAT it tests,
    never from its position in the list. Addresses without the host, so a new port keeps the ID."""
    import hashlib

    from .change_detection import page_key
    kind = c.get("journey") or c.get("feature_kind") or c.get("kind") or c.get("type") or ""
    if c.get("size") == "small":
        key = c["id"]
    elif c.get("parts"):  # a built-in large case: the pages + steps it is made of
        key = "|".join(sorted(f"{p['page']}:{p['step']['id']}" for p in c["parts"]))
    elif c.get("spec"):  # a journey: where it starts and what it uses
        s = c["spec"]
        key = json.dumps({k: (page_key(v) if k in ("url", "start", "href") else v) for k, v in s.items()
                          if k in ("url", "start", "form", "add", "search", "logged_in", "user", "selector", "href",
                                   "box", "next", "pattern", "picks", "rule", "a", "b", "role", "expect",
                                   "width")}, sort_keys=True)
    else:  # an AI case: its title (the AI may word it differently next time - then it counts as a new case)
        key = re.sub(r"\W+", " ", (c.get("title") or "").lower()).strip()
    return "TC-" + hashlib.sha1(f"{kind}|{key}".encode(), usedforsecurity=False).hexdigest()[:8].upper()


NEGATIVE_WORDS = re.compile(r"wrong|invalid|refus|reject|empty|nothing (is |was )?found|not found|no result|"
                            r"is blocked|must not|lower role|denied", re.I)
EDGE_WORDS = re.compile(r"boundar|maximum|minimum|too long|limit|middle|last page|special character|unusual|"
                        r"zero|only spaces|whitespace|phone width|every page|every link", re.I)


def scenario_of(c: dict) -> str:
    """The kind of scenario a test case is - the way a tester sorts them (and TestOptim says it writes them):
    happy (it works the normal way) | negative (a wrong / empty / refused input or a forbidden action) | edge (limits,
    first / last items, unusual values, phone width) | workflow (a journey across pages) | state (a control switches
    what the page shows: tabs, panels, learned behaviour) | blocked (a protected action, never performed)."""
    t, title = (c.get("type") or "").lower(), str(c.get("title") or "")
    if c.get("blocked"):
        return "blocked"
    if t == "negative" or NEGATIVE_WORDS.search(title):
        return "negative"
    if c.get("id") == "site_input_values" or EDGE_WORDS.search(title) or c.get("kind") in ("items", "mobile"):
        return "edge"
    if c.get("journey") or c.get("ai") or c.get("kind") in ("crud", "flow"):
        return "workflow"
    if c.get("kind") in ("learned", "pair") or re.search(r"\b(tab|tabs|panel|opens|toggle|switch)", title, re.I):
        return "state"
    return "happy"


def finalize_cases(cases: list[dict], state: dict) -> list[dict]:
    """Give every test case all the fields of a structured test case (Excel, report, regression comparison).
    Safe to call again: existing values are kept, execution fields are reset for this run."""
    auth_pages = {p["slug"] for p in state.get("app_map", []) if p.get("auth")}
    used = set()
    for c in cases:
        tc = c.get("tc_id") or _stable_id(c)
        while tc in used:  # (two cases testing exactly the same thing: keep both, distinct IDs)
            tc += "b"
        used.add(tc)
        pages = c.get("pages") or [s.strip() for s in str(c.get("page", "")).split(",") if s.strip()]
        feature, element = SMALL_FEATURE.get(c["id"]) or JOURNEY_FEATURE.get(c.get("journey")) or (
            ("User journey (AI)", "several controls") if c.get("ai") else
            (FEATURE_NAME.get(c.get("feature_kind"), "Feature"), c["spec"].get("name") or "the feature")
            if c.get("kind") == "feature" else ("What the control does (learned)", c["spec"].get("name") or "a control")
            if c.get("kind") == "learned" else ("Protected action", "a consequential button")
            if c.get("blocked") else ("Page features", "the page's controls"))
        if c.get("journey") == "form":
            feature = f"Form on {pages[0] if pages else 'a page'}"
        if c.get("kind") in ("form", "crud", "cleanup", "pair", "items", "role", "mobile"):
            feature, element = {"role": ("User roles", f"role {(c.get('spec') or {}).get('role')}"),
                                "mobile": ("Phone width (390 x 844)", "the page at phone size"),
                                "items": ("Items in depth", "the item list and the items' pages"),
                                "form": ("Form", (c.get("spec") or {}).get("box_name") or "every box"),
                                "crud": ("Create / edit / delete a record", "the form and the list"),
                                "cleanup": ("Test data cleanup", "the records this run created"),
                                "pair": ("Rule between fields", " + ".join(
                                    x for x in ((c.get("spec") or {}).get("a_name"), (c.get("spec") or {}).get("b_name"))
                                    if x))}[c["kind"]]
        pre = ["The website is reachable"]
        pre.append("Not logged in (a visitor)" if c.get("guest") or not (set(pages) & auth_pages)
                   else "Logged in with the test account")
        if c.get("journey") == "login" or c.get("kind") in ("login_ok",):
            pre.append("A test account is given (it is read at run time, never written into the scripts)")
        if c["id"] == "site_input_values" or c.get("journey") == "form":
            pre.append("Forms are never sent: values are only typed in and checked")
        if c.get("kind") in ("form", "crud", "cleanup"):
            pre.append("Nothing is sent: the write guard stops what the page sends ('would send' = accepted)"
                       if (c.get("spec") or {}).get("mode") == "guard" else
                       "Staging: the form IS sent - with tagged test data (qa-<run>-<n>), cleaned up after the run")
        if c.get("kind") == "pair":
            pre.append("A common convention, not a written rule: if the site breaks it, you are asked whether that is "
                       "allowed" + ("; nothing is sent (write guard)" if (c.get("spec") or {}).get("guard") else ""))
        risk = c.get("risk") or ("high" if c.get("journey") in ("login", "form", "shop") or c["id"] == "site_input_values"
                                 or (c.get("priority") == "high" and c.get("type") in ("end-to-end", "negative"))
                                 else "low" if c["id"] == "site_images" else "medium")
        # Preserve explicit verification credit; default interaction for unsubmitted form journeys / input-only.
        from ..assert_strength import verification_credit
        credit = c.get("verification") or verification_credit(c)
        c.update(tc_id=tc, feature=c.get("feature") or feature, element=c.get("element") or element,
                 priority=c.get("priority") if c.get("priority") in LEVELS else "medium", risk=risk,
                 verification=credit,
                 preconditions=c.get("preconditions") or pre,
                 test_data_ref=c.get("test_data_ref") or (
                     "test account (TEST_USERNAME / TEST_PASSWORD) - never stored in the scripts"
                     if c.get("journey") == "login" else "built-in test values (see Test Data)" if c.get("test_data")
                     else "none"),
                 requirement=c.get("requirement") or (
                     "Your workflows (Requirements)" if c.get("ai") and settings.requirements else
                     f"User journey: {c['journey']}" if c.get("journey") else
                     "Site-wide quality check" if c.get("size") == "small" else "Everything a user can do on these pages"),
                 automation_status="Pending", execution_status="Not run", actual_result="", evidence=[],
                 skip_reason=c.get("skip_reason") or "")
        c["steps"] = [str(s) for s in c.get("steps") or []]
        c["scenario"] = c.get("scenario") or scenario_of(c)
        c.setdefault("page", ", ".join(pages))
        c.setdefault("url", "")
        c.setdefault("type", "functional")
        c.setdefault("test_data", "")
    return cases


def validate_case(c: dict) -> list[str]:
    """Schema check of one structured test case -> list of problems (empty = valid)."""
    problems = [f"missing field '{f}'" for f in CASE_FIELDS if f not in c]
    if not re.fullmatch(r"TC-[0-9A-F]{8}b*", str(c.get("tc_id", ""))):
        problems.append("tc_id must look like TC-1A2B3C4D")
    if not (isinstance(c.get("steps"), list) and c["steps"] and all(isinstance(s, str) for s in c["steps"])):
        problems.append("steps must be a non-empty list of texts")
    for f in ("priority", "risk"):
        if c.get(f) not in LEVELS:
            problems.append(f"{f} must be high, medium or low")
    if not str(c.get("title", "")).strip() or not str(c.get("expected", "")).strip():
        problems.append("title and expected result are required")
    if not isinstance(c.get("preconditions"), list) or not isinstance(c.get("evidence"), list):
        problems.append("preconditions and evidence must be lists")
    return problems


# ---------------------------------------------------------------- feature tests + protected actions (every page)

QTY_HINT = re.compile(r"\b(qty|quantity|quantities|amount)\b|qty|quantity", re.I)


def _quantity_box(p: dict) -> str:
    """The product's own quantity box (a number box, or a text box named / labelled quantity) - '' if none."""
    for i in shown_first(p).get("inputs", []):
        t = (i.get("type") or "text").lower()
        hint = f"{i.get('name')} {i.get('id')} {i.get('label')} {i.get('placeholder')}"
        if i.get("selector") and not i.get("readonly") and not i.get("disabled") and t in ("number", "text", "") \
                and (t == "number" or QTY_HINT.search(hint)) and not re.search(r"search|keyword", hint, re.I):
            return i["selector"]
    return ""


def site_feature_cases(pages: list[dict]) -> list[dict]:
    """One test case per feature the inspector found (filter, sort, next page, wishlist, long search ...).
    Each case says what to do and the rule its result is checked against (backend/features.py)."""
    from ..features import page_features
    from ..registry import page_pattern
    out, seen = [], set()
    cart = next((c for c in pages if c.get("page_type") == "cart"), None)
    for p in pages:
        page = _page_name(p)
        feats = page_features(p)
        listed = any(f["kind"] == "items" for f in feats)
        qty = _quantity_box(p)
        if qty and cart and p.get("page_type") == "product" and ("quantity", page_pattern(p)) not in seen:
            seen.add(("quantity", page_pattern(p)))  # valid / invalid quantity -> what the CART gets (test env.)
            add = features(p)["add"]
            if add and settings.environment in ("test", "staging"):
                n = len(out) + 1
                out.append({"id": f"feature_{n}", "kind": "feature", "feature_kind": "quantity", "type": "boundary",
                            "priority": "high" if p.get("auth") else "medium",
                            "title": f"Quantity: a valid quantity reaches the cart, an invalid one does not ({_short(p)})",
                            "spec": {"url": p["url"], "qty": qty, "add": add, "cart_url": cart["url"],
                                     "guest": not p.get("auth")},
                            "steps": [f"Open {page}", "Type 2 into the quantity box and add the item to the cart",
                                      "Open the cart: the item's quantity went up by 2",
                                      "Type -1 into the quantity box and add the item again",
                                      "Open the cart: the quantity did not go down (-1 is refused or corrected)",
                                      "Remove the line this test added (cleanup)"],
                            "expected": "A valid quantity (2) is what the cart gets; an invalid one (-1) is refused or "
                                        "corrected - never put in the cart as such",
                            "page": p["slug"], "url": p["url"], "pages": [p["slug"], cart["slug"]],
                            "guest": not p.get("auth"), "test_data": "2 (valid), -1 (invalid)",
                            "files": ["test_features.py"], "tests": [f"test_feature_{n}"]})
        for f in feats:  # (once per page pattern: /shop?page=2 and /shop?category=x are the same page; the header's
            k = f["kind"]  # search box is one box on every page: once)
            key = (k, f.get("selector")) if k == "search" else (k, page_pattern(p))
            if k in ("filter", "sort", "pagination") and not listed:
                continue  # an empty list (a category with no products): nothing to filter, sort or page through
            if key in seen:
                continue
            items = ((p.get("itemLinks") or {}).get("selector")) or ""
            spec = {"url": p["url"], "items": items, "guest": not p.get("auth")}
            if k == "filter" and (f.get("links") or f.get("boxes")):
                opt = (f["links"] or [{}])[0]
                spec.update(href=opt.get("href", ""), box=(f.get("boxes") or [""])[0], boxes=(f.get("boxes") or [])[:4],
                            name=" / ".join((f["names"] or ["filter"])[:4 if not opt else 1]))
                case = ("Filtering by '{name}' changes the list", f"Use the '{spec['name']}' filter, then clear it",
                        "The list of items changes to match the filter; clearing the filter shows the full list again")
                pages_feature = next((x for x in feats if x["kind"] == "pagination"), None)
                if opt.get("href") and pages_feature and len(out) < 200:  # a filter + its pages: the filter must stay
                    out.append({"id": f"feature_{len(out) + 1}", "kind": "feature", "feature_kind": "filter_pages",
                                "type": "positive", "priority": "medium",
                                "title": f"Going to the next page keeps the '{spec['name']}' filter ({_short(p)})",
                                "spec": dict(spec), "steps": [f"Open {page}", f"Use the '{spec['name']}' filter",
                                                              "Go to the next page of results"],
                                "expected": "The next page still shows only filtered items (the filter is kept)",
                                "page": p["slug"], "url": p["url"], "pages": [p["slug"]], "guest": not p.get("auth"),
                                "test_data": "", "files": ["test_features.py"], "tests": [f"test_feature_{len(out) + 1}"]})
            elif k == "sort":
                spec.update(selector=f["selector"], options=f["options"], labels=f.get("labels") or f["options"],
                            name=f["name"])
                case = ("Sorting with '{name}' puts the items in that order", f"Choose each option in '{f['name']}'",
                        "Each option sorts the items the way its label says (price low to high, name A-Z ...); "
                        "the chosen option stays selected")
            elif k == "pagination":
                spec.update(href=f["links"][0]["href"], selector=f["links"][0].get("selector", ""),
                            name=f["links"][0]["text"] or "next page")
                case = ("'{name}' shows other items", f"Open '{spec['name']}'", "Other items are shown")
            elif k == "wishlist":
                spec.update(selector=f["selector"], name=f["name"])
                case = ("'{name}' saves the item (test account)", f"Click '{f['name']}'",
                        "The page confirms it (message or count changes); no errors")
            elif k == "search":
                spec.update(selector=f["selector"], name=f["name"])
                case = ("Search with a 500-character text does not break the page", "Type 500 letters, press Enter",
                        "The page keeps working: no error page, no JavaScript error")
            else:
                continue
            seen.add(key)
            title, step, expected = case
            n = len(out) + 1
            out.append({"id": f"feature_{n}", "kind": "feature", "feature_kind": k, "type": "positive"
                        if k != "search" else "boundary", "priority": "high" if p.get("auth") else "medium",
                        "title": f"{title.format(name=spec.get('name', ''))} ({_short(p)})", "spec": spec,
                        "steps": [f"Open {page}", step], "expected": expected, "page": p["slug"], "url": p["url"],
                        "pages": [p["slug"]], "guest": not p.get("auth"), "test_data": "500 × 'a'" if k == "search" else "",
                        "files": ["test_features.py"], "tests": [f"test_feature_{n}"]})
    return out


# ---------------------------------------------------------------- what exploring LEARNED each control does
LEARNED_TITLE = {
    "message": "'{name}' shows its message ('{msg}')", "navigates": "'{name}' opens {to}",
    "value": "'{name}' changes its value", "panel": "'{name}' opens its panel ({revealed})",
    "text": "'{name}' changes what the page shows", "list": "'{name}' changes the list",
    "picture": "'{name}' shows another picture", "nothing": "'{name}' gives a visible response when clicked",
    "scroll": "'{name}' moves the page (scrolls)",
}
# doing nothing visible can be right for these: nothing to close / cancel, no page or slide before the first ...
QUIET_OK = re.compile(r"^\s*(close|cancel|dismiss|back|go back|prev(ious)?( page)?|next( page)?|first|last|skip|later|"
                      r"not now|no,? thanks|got it|ok|okay|hide|show less|less|reset|clear( all| filters?)?|refresh|"
                      r"reload|update( cart)?|search|go|[×✕✖xX<>‹›«»←→]|\d+)\s*$", re.I)


def _must_respond(b: dict | None, name: str) -> bool:
    """Is 'it did nothing visible' a defect for this control? Only for a control made to DO something: a real button
    (or a link that runs an action: href '#' / javascript:) - not a link to an address (it may be this very page), a
    box to type in, a tab / page / slide arrow, a pointer-only element, or a close / cancel / back control. And only
    when we know what it is for: a control without a real name (an icon whose only name is its CSS classes, like
    'btn btn orange' - e.g. the 'grid view' button of a list already shown as a grid) may rightly do nothing."""
    b = b or {}
    if (b.get("kind") or "") in ("next", "slide", "tab", "collapse") or b.get("custom") or QUIET_OK.match(name or ""):
        return False
    if b.get("named") is False:
        return False
    tag, kind = (b.get("tag") or "").lower(), (b.get("type") or "").lower()
    if tag in ("input", "select", "textarea") and kind not in ("button", "submit", "image"):
        return False
    if tag == "a":
        href = re.search(r'\bhref\s*=\s*"([^"]*)"', b.get("html") or "")
        target = href.group(1).strip() if href else ""
        if target and target != "#" and not target.lower().startswith("javascript:"):
            return False
    return bool(tag)


HISTORY_BACK = re.compile(r"history\.(back|go)\s*\(\s*(-|\))", re.I)


def learned_cases(pages: list[dict]) -> list[dict]:
    """One test per control whose effect was learned while exploring: it must do the same again (an EXPLORATORY
    check - the expected result is what the website did, not a business rule). Three exceptions are rules:
    an error message is never right, a visitor asked to sign in 'needs a test account' (not passed), and a control
    that did nothing visible must give some response (only a control made to do something - see _must_respond; for
    the others 'nothing visible' is no evidence either way: no test, the registry says inconclusive).
    Controls with their own feature test are left to it."""
    from ..features import page_features
    from .discovery import _pattern
    out, done = [], set()
    for p in pages:
        if p.get("page_type") == "cart":
            continue  # what its controls did depended on what the cart held while exploring (see CART_STATE)
        f = features(p)
        covered = {f[k] for k in ("search", "add", "qty", "plus", "minus") if f.get(k)}
        for x in page_features(p):
            covered |= {x.get("selector")} | set(x.get("boxes") or []) | {l.get("selector") for l in x.get("links") or []}
        lf = login_form(p)  # (its button: 'Login with a wrong password is rejected' - 'Invalid credentials' is right)
        if lf:
            covered |= {lf.get("submit")}
        by_sel ={b.get("selector"): b for b in p.get("buttons", []) + p.get("inputs", [])}
        for b in p.get("behaviour", []):
            if re.search(r"\bloaded\s*:|\b\d+(?:\.\d+)?\s*%|video player is loading|remaining time", b.get("control") or "", re.I):
                continue  # progress/timer text is not a stable action or a business oracle
            key = (b.get("control"), b.get("selector"))
            if b.get("effect") in ("error", None) or b.get("selector") in covered or key in done \
                    or b.get("risk") == "protected" or len(out) >= 80:
                continue
            done.add(key)
            if HISTORY_BACK.search((by_sel.get(b["selector"]) or {}).get("html") or ""):
                continue  # ('Back to the results' = the browser's Back: a test that opens this page has no history)
            name, eff, tone = b["control"], b["effect"], b.get("tone") or ""
            if eff == "nothing" and not _must_respond(by_sel.get(b["selector"]), name):
                continue
            opener = b.get("revealed_by")
            opener_name = (by_sel.get(b["selector"]) or {}).get("revealed_by_name") or "its opener"
            to = (_pattern(b["to"], False) or (0, urlparse(b["to"]).path))[1] if b.get("to") else ""
            if tone == "error":
                title, expected, oracle = (f"'{name}' works without an error message", "No error message: while "
                                           f"exploring the website said '{b.get('message', '')[:80]}'", "rule")
            elif tone == "login_needed" and not p.get("auth"):
                title, expected, oracle = (f"'{name}' as a visitor asks to sign in (needs a test account)",
                                           "As a visitor the website asks to sign in: this feature needs a test "
                                           "account (it is not counted as working)", "rule")
            else:
                title = LEARNED_TITLE[eff].format(name=name, msg=(b.get("message") or "")[:50], to=to or "another page",
                                                  revealed=", ".join(b.get("revealed") or [])[:60])
                expected = {"message": f"The same kind of message appears again ('{(b.get('message') or '')[:80]}')",
                            "navigates": f"It opens {to}", "value": "Its value changes, as it did while exploring",
                            "panel": "Its panel opens: " + ", ".join(b.get("revealed") or [])[:80],
                            "text": "What the page shows changes", "list": "The list changes",
                            "picture": "Its widget shows another picture, as it did while exploring",
                            "nothing": "Something visible happens (a message, a change) - while exploring nothing did",
                            "scroll": "The page scrolls, as it did while exploring",
                            }[eff]
                oracle = "rule" if eff == "nothing" else "observed"
            act = {"select": f"Choose another option in '{name}'", "tick": f"Tick '{name}'"}.get(b.get("action"),
                                                                                                  f"Click '{name}'")
            n = len(out) + 1
            out.append({
                "id": f"learned_{n}", "kind": "learned", "type": "exploratory" if oracle == "observed" else "positive",
                "oracle": oracle, "priority": "medium", "title": f"{title} ({_short(p)})",
                "steps": [f"Open {_page_name(p)}"] + ([f"Click '{opener_name}' first"] if opener else []) + [act],
                "expected": expected, "page": p["slug"], "url": p["url"], "pages": [p["slug"]],
                "guest": not p.get("auth"), "test_data": "",
                "spec": {"url": p["url"], "name": name, "selector": b["selector"], "action": b.get("action", "click"),
                         "value": b.get("value"), "effect": eff, "message": b.get("message") or "", "tone": tone,
                         "to": to, "revealed": b.get("revealed") or [], "opener": opener,
                         "openers": opener_path(p, b["selector"], opener), "guest": not p.get("auth"),
                         # what it showed while exploring ('Total users: 23') - not a clock / a date, which change
                         "added": [a for a in (b.get("added") or []) if a and len(a) < 120
                                   and not re.search(r"\d{1,2}:\d{2}|\b(19|20)\d\d\b|\bloaded\s*:|\d+(?:\.\d+)?\s*%|video player is loading", a, re.I)][:3]
                         if eff in ("text", "list") else []},
                "files": ["test_learned.py"], "tests": [f"test_learned_{n}"]})
    return out


def blocked_cases(pages: list[dict]) -> list[dict]:
    """Consequential actions the tester found but never clicks (pay, order, delete, send, save ...) - reported as
    BLOCKED test cases, so it is visible what still needs a human with permission."""
    from ..features import page_features
    out, seen = [], set()
    for p in pages:
        for f in page_features(p):
            for a in f.get("actions", []) if f["kind"] == "protected" else []:
                if a["text"].lower() in seen or len(out) >= 20:
                    continue
                seen.add(a["text"].lower())
                out.append({"id": f"blocked_{len(out) + 1}", "kind": "blocked", "blocked": True, "type": "workflow",
                            "priority": "high", "title": f"'{a['text']}' on {_short(p)} - not run (protected action)",
                            "steps": [f"Open {_page_name(p)}", f"Click '{a['text']}'"],
                            "expected": "Needs explicit approval and a safe test environment before it can be tested",
                            "skip_reason": "Blocked: protected action (it could pay, order, delete, send or change "
                                           "data) - never clicked without ALLOW_ACTIONS naming the class "
                                           "(and TEST_PAYMENT=1 for pay, staging only)",
                            "page": p["slug"], "url": p["url"], "pages": [p["slug"]], "guest": not p.get("auth"),
                            "files": [], "tests": []})
    return out


def test_design_agent(state: QAState) -> QAState:
    if state.get("target_type") == "mobile":
        from ..android_design import design_cases
        return design_cases(state)
    if state.get("contract_only"):
        from ..android_design import normalize_case
        from ..qa_contracts import contract_cases, parse_contract

        contract_path = Path(state["run_dir"]) / ".private" / "qa_contract.json"
        contract = parse_contract(contract_path.read_text(encoding="utf-8"))
        cases = [normalize_case(case) for case in contract_cases(contract)]
        for case in cases:
            case.update(target_type="web", platform="web", url=state["url"], page="contract",
                        pages=["contract"], files=["qa_contracts.json"], tests=["test_" + case["id"]],
                        script_source="contract")
        Path(state["run_dir"], "test_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
        write_workbook(Path(state["run_dir"]), cases)
        note = f"Contract-only design: {len(cases)} explicitly approved flow case(s); built-in site checks were not added."
        print("  [test-design] " + note)
        return {"test_cases": cases, "log": state.get("log", []) + [note]}
    mark_first_seen_inputs(state["app_map"])
    pages = [p for p in state["app_map"] if page_testable(p)]
    pages.sort(key=lambda p: not p.get("auth"))  # the app behind the login first (stable: crawl order kept)
    if settings.reuse_tests:  # regression run: the same test cases as last time (their scripts are run again)
        from .change_detection import saved_tests
        saved = saved_tests(state["site_key"], from_run=settings.reuse_from_run or None)
        if saved:
            cases = finalize_cases(saved["cases"], state)
            _link_registry(state, cases)
            src = saved["meta"].get("source_run") or saved["meta"].get("date", "?")
            print(f"  [test-design] regression run: re-using the {len(cases)} test cases of {src}")
            Path(state["run_dir"], "test_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
            write_workbook(Path(state["run_dir"]), cases)
            return {"test_cases": cases, "log": state.get("log", []) + [
                f"Test design: regression run - the {len(cases)} test cases of {src} "
                "are run again (no new test cases)."]}
        print("  [test-design] regression run asked, but no saved tests for this site/run - writing new ones")
    data, typed = [], set()
    for p in pages:  # (a box on many pages - the footer's newsletter box - is typed into once, on the first page)
        own = [c for c in data_cases(p) if (c["selector"], c["field"]) not in typed]
        data += [dict(c, page=p["slug"], url=p["url"]) for c in own]
        typed.update((c["selector"], c["field"]) for c in own)
    # the search tests look for a word of a REAL item of this website (not a heading like 'Welcome' or 'Home')
    word = site_search_word(pages)
    cards = list(dict.fromkeys(s for p in pages if (s := (p.get("itemLinks") or {}).get("selector"))))[:6]
    items = site_item_pages(pages)
    for p in state["app_map"]:
        p["site_word"], p["site_cards"], p["site_items"] = section_search_word(p, pages, word), cards, items

    # incremental (a very large website, run again): only the pages that are new or whose design / controls changed are
    # fully tested again; the unchanged ones get the site-wide (smoke) checks
    full = pages
    ch = state.get("changes") or {}
    if settings.incremental and ch and not ch.get("first_run"):
        status = ch.get("page_status") or {}
        full = [p for p in pages if status.get(p["slug"], "new") in ("new", "changed")]
        print(f"  [test-design] incremental: {len(full)} new / changed page(s) fully tested, {len(pages) - len(full)} "
              "unchanged page(s) smoke-checked only")

    # every page gets its own test cases - no fixed number: journeys across pages, every feature found, one focused
    # check per feature / control (each with its own result), the AI's extra journeys, then the site-wide checks
    journeys = builtin_journeys(full, limit=40) if full else []
    feats = site_feature_cases(full)
    learned = learned_cases(full)  # every control whose effect exploring learned: it must do it again
    checks = builtin_checks(full) if full else []
    ai, mode = [], "built-in rules"
    if full and llm_enabled():
        try:
            ai, mode = ai_flows(full), "built-in rules + AI"
        except (LLMError, json.JSONDecodeError, ValueError) as e:
            print(f"  [test-design] AI failed: {e} — using built-in rules")
            mode = "built-in rules (the AI failed)"
    from ..my_tests import load as load_my_tests  # your own tests in plain English (kept per website)
    mine = my_test_cases(pages, load_my_tests(state.get("site_key") or ""), start=len(ai) + 1)
    small = small_checks(pages, data) if pages else []
    blocked = blocked_cases(pages)
    # data forms: valid / wrong values (nothing is sent unless staging) + staging's create -> edit -> delete
    from ..forms import cleanup_case, crud_cases, form_cases
    forms = form_cases(full)
    crud = crud_cases(full)
    # rules between fields (an end date before its start, From = To, a count that must change the total ...)
    from ..form_rules import ai_suggestions, pair_cases, step_order_cases
    pairs = pair_cases(full, ai_suggestions(full)) + step_order_cases(full)  # (+ a multi-step form's later step alone)
    # items in depth: the first / middle / last of each list, a filter's items, the next page, more items smoke-checked
    from ..items import item_cases
    items_ = item_cases(full, state.get("crawl"))
    # several user roles: what each role may open - and a lower role is refused an admin page
    from ..roles import role_cases
    roles_ = role_cases(state)
    # phone width: the controls only a phone shows (a hamburger menu) are tested at that size
    from ..mobile import mobile_cases
    mobile_ = mobile_cases(full)
    # (your own tests first: MAX_TEST_CASES never cuts them)
    designed = mine + journeys + feats + learned + checks + ai + crud + forms + pairs + items_ + roles_ + mobile_
    small = small + cleanup_case(crud)  # (never cut by MAX_TEST_CASES: what a staging run created must be removed)

    def _completion_rank(c: dict) -> int:
        """Prefer finishing non-pay work; cut exploratory / checkout-ish titles first when over budget."""
        blob = f"{c.get('title', '')} {c.get('id', '')} {c.get('expected', '')}".lower()
        if any(w in blob for w in ("checkout", "check-out", "pay now", "place order", "confirm payment",
                                   "/payment", "/checkout")):
            return 2
        if c.get("ai") and c.get("type") == "exploratory":
            return 1
        return 0

    designed = sorted(designed, key=_completion_rank)
    room = max(0, settings.max_test_cases - len(small) - len(blocked))
    if len(designed) > room:
        print(f"  [test-design] {len(designed) - room} test case(s) left out: MAX_TEST_CASES={settings.max_test_cases} "
              f"(non-pay work kept ahead of exploratory/checkout-ish titles)")
    cases = finalize_cases(designed[:room] + small + blocked, state)
    bad = {c["tc_id"]: validate_case(c) for c in cases if validate_case(c)}
    if bad:  # (should never happen - a case without its fields can't be reported correctly)
        print(f"  [test-design] {len(bad)} test case(s) are incomplete: {bad}")
    summary = (f"{len(cases)} test cases ({mode}): {len(journeys)} journeys, {len(feats)} feature tests, "
               f"{len(learned)} learned-behaviour tests, "
               f"{len(checks)} focused checks, {len(ai)} AI journeys, {len(mine)} of your own tests, "
               f"{len(small)} site-wide checks, "
               f"{len(blocked)} blocked (protected actions) - for {len(pages)} pages "
               f"({sum(1 for p in pages if p.get('auth'))} behind the login)"
               + (f"; the search tests look for '{word}'" if word else ""))
    print(f"  [test-design] {summary}")
    _link_registry(state, cases)

    Path(state["run_dir"], "test_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    write_workbook(Path(state["run_dir"]), cases)  # Excel copy; results are added by the Report step
    return {"test_cases": cases, "app_map": state["app_map"], "cases_left_out": max(0, len(designed) - room),
            "log": state.get("log", []) + [f"Test design: {summary}."]}


def _link_registry(state: QAState, cases: list[dict]) -> None:
    """Every test case -> the registry features it tests (each feature lists its test cases)."""
    from .. import registry
    reg = registry.load(state["run_dir"]) or registry.build(state.get("app_map", []), state.get("crawl") or {})
    registry.link_tests(reg, cases)
    if llm_enabled():  # (one call: names for people - the checks stay rule-based)
        try:
            n = ai_feature_labels(reg)
            print(f"  [test-design] the AI named the feature of {n} learned control(s) - from the evidence only")
        except LLMError as e:
            print(f"  [test-design] AI feature names skipped ({str(e)[:120]}) - the built-in names are used")
    registry.save(reg, state["run_dir"])
    linked = sum(1 for f in reg["features"].values() if f["tests"])
    print(f"  [test-design] {linked} of {len(reg['features'])} registered feature(s) / control(s) have a test case")
