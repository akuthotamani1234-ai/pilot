"""Inspecting a page: what KIND of page is it, and which FEATURES does it really have?

Nothing is assumed about a particular website: everything comes from what the crawler found on the page
(its address, headings, links, boxes, buttons, forms, repeated item cards). Only features that are really
there are listed - nothing is invented.
"""
import re
from urllib.parse import parse_qsl, urlparse

from .actions import action_risk

FILTER_PARAM = re.compile(r"^(category|cat|brand|colou?r|size|type|filter|tag|price|rating|dept|department|"
                          r"collection|gender|material)$", re.I)
# a filter checkbox: one of those words anywhere in its name / id / test id (data-test="category-01M5...")
FILTER_BOX = re.compile(r"\b(categor(y|ies)|brands?|colou?rs?|sizes?|filters?|tags?|price|rating|dept|department|"
                        r"collection|gender|material)\b", re.I)
SORT_HINT = re.compile(r"sort|order ?by|arrange", re.I)
OPTION_HINT = re.compile(r"\b(size|colou?r|variant|option|style|capacity|storage|model|flavou?r)\b", re.I)
PAGE_PARAM = re.compile(r"^(page|p|pg|pagenum|start|offset)$", re.I)
WISHLIST = re.compile(r"wish ?list|save for later|favou?rite|add to list", re.I)
ORDER_LINK = re.compile(r"/orders?/[^/?#]+|order[ #-]?(no\.?|number|#)?\s*\d|view order|order details", re.I)

PAGE_WORDS = [  # (page type, words in the address or the main heading)
    ("cart", r"\b(cart|basket|trolley|shopping bag)\b"),
    ("checkout", r"\b(checkout|check out)\b"),
    ("orders", r"\b(orders?|order history|purchases)\b"),
    ("wishlist", r"\b(wish ?list|favou?rites)\b"),
    ("addresses", r"\b(address(es)?|address book)\b"),
    ("account", r"\b(account|settings|preferences|my profile)\b|^ ?profile\b"),
    ("dashboard", r"\b(dashboard|overview)\b|^ ?home$"),
    ("admin", r"\b(admin|administration)\b"),
]


def _words(p: dict) -> str:
    """The page's address as words (/my-account/orders -> 'my account orders'; index.php?rt=checkout/cart ->
    'index.php checkout cart': the route that picks the page). Headings are NOT used: a Terms page that mentions
    'payment' is not a checkout."""
    from .agents.discovery import _query_route
    u = urlparse(p.get("final_url") or p.get("url") or "")
    route = " ".join(r.partition("=")[2] for r in _query_route(u.query))
    return f"{u.path} {route}".lower().replace("/", " ").replace("-", " ").replace("_", " ")


def _id_items(p: dict) -> bool:
    """Most listed items open pages with an id in the address (/product/12, /p/abc123): a real list of things."""
    from .agents.discovery import _pattern
    links = (p.get("itemLinks") or {}).get("links") or []
    with_id = [l for l in links if "{id}" in ((_pattern(l.get("href", ""), False) or (0, ""))[1])]
    return len(links) >= 3 and len(with_id) >= len(links) / 2


def _one_item_page(p: dict, f: list[dict]) -> bool:
    """ONE 'Add to cart' (not one per listed item) on an address with an id (/product/01M5...): a product page,
    even when it also lists 'related products' below."""
    from .agents.discovery import _pattern
    add = next((x["selector"] for x in f if x["kind"] == "add_to_cart"), None)
    count = next((b.get("count") or 1 for b in p.get("buttons", []) if b.get("selector") == add), 1)
    own = _pattern(p.get("final_url") or p.get("url") or "", False)
    return count <= 1 and bool(own) and "{id}" in own[1]


def page_type(p: dict) -> str:
    """listing / product / cart / checkout / orders / order_detail / wishlist / addresses / account / dashboard /
    admin / login / register / form / content."""
    from .agents.discovery import _auth_link
    from .auth import login_form
    url = p.get("final_url") or p.get("url") or ""
    if _auth_link(url) and re.search(r"register|sign-?up|create", url, re.I):
        return "register"  # (before 'login': a sign-up form can have just one password box)
    if login_form(p) and not p.get("auth"):
        return "login"
    if not p.get("auth") and any(sum(1 for x in fm.get("fields", []) if x.get("type") == "password") >= 2
                                 for fm in p.get("forms", [])):
        return "register"  # (a password + its repetition, as a visitor: a sign-up form)
    words, f = _words(p), page_features(p)
    kinds = {x["kind"] for x in f}
    if re.search(r"/orders?/[^/?#]+$", urlparse(url).path):
        return "order_detail"
    for kind, rx in PAGE_WORDS:
        if re.search(rx, words):
            return kind
    if "add_to_cart" in kinds and (max(len((p.get("itemLinks") or {}).get("links") or []),
                                       (p.get("itemLinks") or {}).get("count", 0)) < 3 or _one_item_page(p, f)):
        return "product"
    # a list of things to browse: items + a way to search / filter / sort / page through them, or items with ids
    if "items" in kinds and (kinds & {"search", "filter", "sort", "pagination"} or _id_items(p)):
        return "listing"
    if any(len(fm.get("fields", [])) >= 3 for fm in p.get("forms", [])):
        return "form"
    return "content"


def _filter_links(p: dict) -> list[dict]:
    """Links that add a filter to the address (?category=fruit, ?brand=x) - not the filter already applied."""
    base = urlparse(p.get("url", ""))
    current = set(parse_qsl(base.query))
    out, seen = [], set()
    for l in p.get("links", []):
        u = urlparse(l.get("href", ""))
        if u.hostname != base.hostname or u.path.rstrip("/") != base.path.rstrip("/"):
            continue
        keys = [k for k, _ in parse_qsl(u.query) if FILTER_PARAM.match(k)]
        if set(parse_qsl(u.query)) <= current:
            continue  # (this filter is the one already shown)
        if keys and l["href"] not in seen and (l.get("text") or "").strip():
            seen.add(l["href"])
            out.append({"href": l["href"], "text": l["text"].split("\n")[0].strip()[:40], "param": keys[0]})
    return out[:8]


def _page_links(p: dict) -> list[dict]:
    """Links to OTHER result pages: 'Next' / '›' first, then ?page=N links that are not the page shown now."""
    now = next((v for k, v in parse_qsl(urlparse(p.get("url", "")).query) if PAGE_PARAM.match(k)), "1")
    nexts, others = [], []
    here = (p.get("final_url") or p.get("url") or "").split("#")[0].rstrip("/")
    for l in p.get("links", []):
        if l.get("section") and (l.get("href") or "").split("#")[0].rstrip("/") == here:
            continue  # a link to a part of THIS page (an image slider's '#carousel' arrows): not another page
        u = urlparse(l.get("href", ""))
        text = (l.get("text") or "").strip()
        page = next((v for k, v in parse_qsl(u.query) if PAGE_PARAM.match(k)), None)
        if re.fullmatch(r"(next|next page|›|»|>)", text, re.I):
            nexts.append({"href": l["href"], "text": text[:20]})
        elif page is not None and page != now:
            others.append({"href": l["href"], "text": text[:20]})
    if not nexts + others:  # pages switched by BUTTONS (« 1 2 3 »), as single-page apps do: no address to open
        for b in p.get("buttons", []):
            text, s = (b.get("text") or "").strip(), b.get("selector") or ""
            if not s or b.get("disabled") or b.get("kind") == "slide":  # (an image slider's arrow: another slide)
                continue
            if re.fullmatch(r"(next|next page|›|»|>)", text, re.I) or re.search(r"pagination-next|page-next", s, re.I):
                nexts.append({"href": "", "selector": s, "text": text[:20] or "next page"})
            elif re.fullmatch(r"[2-9]", text) and re.search(r"page", s, re.I):
                others.append({"href": "", "selector": s, "text": f"page {text}"})
    return (nexts + others)[:5]


def shown_first(p: dict) -> dict:
    """The page as it opens: without the controls that only appear after another one is used (`revealed_by`) -
    those are tested with their opener (the learned tests), not on a freshly opened page."""
    if not any(x.get("revealed_by") for x in p.get("buttons", []) + p.get("inputs", [])):
        return p
    return dict(p, buttons=[b for b in p.get("buttons", []) if not b.get("revealed_by")],
                inputs=[i for i in p.get("inputs", []) if not i.get("revealed_by")])


def page_features(p: dict) -> list[dict]:
    """The features this page really has (each with what a test needs to use it)."""
    from .agents.test_design import _box_name, features as basic
    p = shown_first(p)
    f, out = basic(p), []
    if f["search"]:
        out.append({"kind": "search", "selector": f["search"], "name": f["search_name"], "word": f["word"]})
    for i in p.get("inputs", []):
        if i.get("suggests") and i.get("selector"):
            out.append({"kind": "suggestions", "selector": i["selector"], "name": _box_name(i)})
            break
    items = p.get("itemLinks") or {}
    item_count = max(len(items.get("links") or []), items.get("count", 0))
    if item_count >= 3:
        out.append({"kind": "items", "selector": items.get("selector"), "count": item_count,
                    "first": (items.get("links") or [None])[0]})
    flinks = _filter_links(p)
    boxes = [i for i in p.get("inputs", []) if (i.get("type") or "") == "checkbox" and i.get("selector")
             and FILTER_BOX.search(f"{i.get('name')} {i.get('id')} {i.get('selector')} {i.get('html')}")]
    if flinks or boxes:
        out.append({"kind": "filter", "links": flinks, "boxes": [b["selector"] for b in boxes[:6]],
                    "names": [x["text"] for x in flinks] or [_box_name(b) for b in boxes[:6]]})
    for i in p.get("inputs", []):
        hint = f"{i.get('name')} {i.get('id')} {i.get('label')}"
        if i.get("tag") == "select" and len(i.get("options") or []) >= 2 and SORT_HINT.search(hint):
            out.append({"kind": "sort", "selector": i["selector"], "name": _box_name(i),
                        "options": [o["value"] for o in i["options"][:6]],
                        "labels": [o.get("text") or o["value"] for o in i["options"][:6]]})  # (the label says the order)
        elif i.get("tag") == "select" and len(i.get("options") or []) >= 2 and OPTION_HINT.search(hint):
            out.append({"kind": "option", "selector": i["selector"], "name": _box_name(i),
                        "options": [o["value"] for o in i["options"][:6]]})
    pages = _page_links(p)
    if pages:
        out.append({"kind": "pagination", "links": pages})
    if f["add"]:
        out.append({"kind": "add_to_cart", "selector": f["add"], "name": f["add_text"]})
    for b in p.get("buttons", []):
        if b.get("selector") and WISHLIST.search(b.get("text") or "") and not b.get("disabled"):
            out.append({"kind": "wishlist", "selector": b["selector"], "name": (b.get("text") or "").strip()[:40]})
            break
    orders = [l for l in p.get("links", []) if ORDER_LINK.search(f"{l.get('href')} {l.get('text')}")
              and not l.get("external") and l.get("href", "").rstrip("/") != p.get("url", "").rstrip("/")]
    if orders:
        out.append({"kind": "order_link", "href": orders[0]["href"], "name": (orders[0].get("text") or "")[:40]})
    protected = {}
    for b in p.get("buttons", []):
        t = (b.get("text") or "").split("\n")[0].strip()
        if (t and action_risk(t, b.get("selector"), role=b.get("role"), kind=b.get("kind"), tag=b.get("tag"))
                == "protected" and not b.get("disabled")):
            protected.setdefault(t.lower(), {"text": t[:40], "selector": b.get("selector")})
    if protected:
        out.append({"kind": "protected", "actions": list(protected.values())[:8]})
    return out
