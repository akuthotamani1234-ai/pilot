"""Items in depth (Step 10) - whatever the items are (products, flights, articles, users, orders):

  open        for each item list: its FIRST, MIDDLE and LAST item open from the list -> the item's page shows the SAME
              name (and the same price / amount when the card shows one), and Back returns to the list
  smoke       up to 10 more items of each kind (sampled by the crawl): they open (status < 400), without JavaScript
              errors or broken pictures
  filter      a filter whose value the cards show (a "Non-stop only" box, flight cards that say "Non-stop" / "1 stop"):
              every item shown after filtering matches it
  pages       the list's next page shows OTHER items than the first
The item pages themselves are tested like any other page (their options, quantity, tabs, gallery, buttons). The values
of one item are compared across pages: list -> its page here, list -> cart in the shopping journey.
"""
import re
from pprint import pformat
from urllib.parse import urlparse

FILTER_WORDS = re.compile(r"\b(only|show|just|filter|by)\b", re.I)


def _lists(pages: list[dict]) -> list[dict]:
    out, seen = [], set()
    for p in pages:
        il = p.get("itemLinks") or {}
        links = [l for l in il.get("links") or [] if l.get("href")]
        if len(links) < 2 or not il.get("selector"):
            continue
        if len({(l.get("text") or "").strip().lower() for l in links}) == 1 \
                and all(urlparse(l["href"]).path == urlparse(p["url"]).path for l in links):
            continue  # 'click here' x3 to this same page with other settings (?mode=random): versions of it, no items
        key = (il["selector"], urlparse(p["url"]).path)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:4]


def _filter_box(p: dict) -> dict | None:
    """A filter checkbox whose word the item cards show ("Non-stop only" -> cards with "Non-stop" / "1 stop")."""
    il = p.get("itemLinks") or {}
    cards = " ".join(il.get("cards") or [l.get("text") or "" for l in il.get("links") or []])
    for i in p.get("inputs", []):
        if (i.get("type") or "") != "checkbox" or not i.get("selector"):
            continue
        word = FILTER_WORDS.sub("", i.get("label") or "").strip(" :-")
        # (only a filter whose value the cards SHOW: some cards have it, some don't - else nothing can be read)
        with_word = [c for c in il.get("cards") or [] if re.search(re.escape(word), c, re.I)] if len(word) >= 3 else []
        if with_word and len(with_word) < len(il.get("cards") or []) and re.search(re.escape(word), cards, re.I):
            return {"selector": i["selector"], "word": word, "label": (i.get("label") or "").strip()}
    return None


def pager_next(controls: list[dict], label) -> dict | None:
    """The pager's Next control. Every button of a pager counts as 'next' (discovery): prefer the real Next, never
    '«' / Previous / page 1 (they don't go forward from the first page)."""
    pager = [b for b in controls if b.get("kind") == "next" and b.get("selector") and not b.get("disabled")
             and not b.get("inert")
             and not re.fullmatch(r"«|‹|<|prev(ious)?( page)?|first|1", label(b).strip(), re.I)]
    return next((b for b in pager if re.fullmatch(r"next|next page|»|›|>", label(b).strip(), re.I)), None) \
        or next(iter(pager), None)


def _next_control(p: dict) -> str | None:
    b = pager_next(p.get("buttons", []), lambda b: (b.get("text") or "").split("\n")[0])
    if b:
        return b["selector"]
    link = next((l for l in p.get("links", []) if re.fullmatch(r"\s*(next|next page|»|›|>)\s*", l.get("text") or "",
                                                                   re.I)), None)
    return f'a[href="{link["href"]}"]' if link else None


def item_cases(pages: list[dict], crawl: dict | None) -> list[dict]:
    out = []

    def case(cid, kind, title, steps, expected, p, spec, priority="high"):
        out.append({"id": cid, "kind": kind, "type": "positive", "priority": priority, "title": title, "steps": steps,
                    "expected": expected, "page": p["slug"] if p else "site", "url": p["url"] if p else "",
                    "pages": [p["slug"]] if p else [], "guest": not (p or {}).get("auth"), "test_data": "",
                    "files": ["test_items.py"], "tests": [f"test_{cid}"], "spec": spec})

    for n, p in enumerate(_lists(pages), start=1):
        hints = [(p.get("itemLinks") or {}).get("selector")]
        where = urlparse(p["url"]).path or "/"
        case(f"items_open_{n}", "items", f"Items of {where}: the first, middle and last open with their own name and price",
             [f"Open {p['url']}", "Open the first, the middle and the last item of the list",
              "Compare its page with its card (name, price)", "Go back"],
             "Each item's page shows the name (and the price) its card shows, and Back returns to the list", p,
             {"url": p["url"], "hints": hints, "picks": ["first", "middle", "last"]})
        f = _filter_box(p)
        if f:
            case(f"items_filter_{n}", "items", f"Filter '{f['label']}': every item shown matches it ({where})",
                 [f"Open {p['url']}", f"Tick '{f['label']}'", "Read every item shown"],
                 f"Every item shown says '{f['word']}' (on its card, or on its own page)", p,
                 dict(f, url=p["url"], hints=hints))
        nxt = _next_control(p)
        if nxt:
            case(f"items_pages_{n}", "items", f"The next page of {where} shows other items",
                 [f"Open {p['url']}", "Note the items", "Go to the next page"],
                 "The next page lists other items than the first", p, {"url": p["url"], "next": nxt, "hints": hints},
                 priority="medium")
    for k, (pattern, t) in enumerate(sorted(((crawl or {}).get("item_types") or {}).items()), start=1):
        if t.get("smoke"):
            case(f"items_smoke_{k}", "items", f"{len(t['smoke'])} more pages like {pattern} open without errors",
                 [f"Open each of {len(t['smoke'])} more pages of {pattern}"],
                 "Each opens (status < 400), with no JavaScript error and no broken picture", None,
                 {"urls": t["smoke"], "pattern": pattern}, priority="low")
    return out


ITEM_HELPERS = r'''
PRICE = re.compile(r'(?:[$€£₹]|\b(?:rs|inr|usd|eur)\.?)\s?(\d[\d,]*(?:\.\d{1,2})?)', re.I)
# a card's link that says what to do, not the item's name ('VIEW POST', 'Read more')
CALL_TO_ACTION = re.compile(r'(view|read|see|open|more|details|learn|go to|continue)\b', re.I)


def _prices(text):
    return [p.replace(',', '') for p in PRICE.findall(text or '')]


def _pick(n, which):
    return {'first': 0, 'middle': n // 2, 'last': n - 1}[which]


def _check_items_open(page, I):
    page.goto(I['url'])
    _settle(page)
    first = _listed(page, hints=I['hints'])
    names, hrefs, cards = first.get('names') or [], first.get('hrefs') or [], first.get('cards') or []
    assert len(names) >= 2, f"the list on {I['url']} shows {len(names)} item(s)"
    done = set()
    for which in I['picks']:
        k = _pick(len(names), which)
        if k in done:
            continue
        done.add(k)
        page.goto(I['url'])
        _settle(page)
        now = _listed(page, hints=I['hints'])
        if k >= len(now.get('names') or []):
            continue
        name, card = now['names'][k], (now.get('cards') or [''] * (k + 1))[k] if now.get('cards') else ''
        link = page.locator(f'[data-qa-item="{k}"]').first
        if link.count():
            link.click()
        else:
            page.goto(now['hrefs'][k])
        _settle(page)
        shown = _product_name(page, None if CALL_TO_ACTION.match(name or '') else name)
        if CALL_TO_ACTION.match(name or ''):  # 'VIEW POST': the item's name is one of its card's own lines
            lines = [l.strip() for l in (card or '').splitlines() if l.strip() and not CALL_TO_ACTION.match(l.strip())]
            assert shown and any(_same_name(shown, l) for l in lines), (
                f"the {which} item ('{name}') opened a page that shows '{shown}' - not a name its card shows {lines[:2]}")
            name = shown
        else:
            assert _same_name(shown, name), f"the {which} item '{name}' opened a page that shows '{shown}'"
        want = _prices(card)[:1]
        if want:
            got = _prices(page.locator('body').inner_text())
            same = [g for g in got if float(g) == float(want[0])]  # (the same amount: 46.5 is 46.50)
            assert same, (f"the {which} item '{name}': its card says {want[0]}, its page shows "
                          f"{got[:4] or 'no price'}")
            assert want[0] in got, (f"the {which} item '{name}': its card writes the price {want[0]}, its page "
                                    f"{same[0]} - the same price, written differently")
        _step_ok(f"the {which} item '{name}' opens with the same name" + (f" and price {want[0]}" if want else ""))
        page.go_back()
        _settle(page)
        back = _listed(page, hints=I['hints'])
        for _ in range(10):  # (a single-page app draws the list again when its data has arrived: up to 5 s)
            if back.get('names'):
                break
            page.wait_for_timeout(500)
            back = _listed(page, hints=I['hints'])
        assert back.get('names'), f"Back from '{name}' did not return to the list"
    assert done


def _check_items_filter(page, I):
    page.goto(I['url'])
    _settle(page)
    box = page.locator(I['selector']).first
    expect(box, 'the filter should be visible').to_be_visible()
    box.check()
    page.wait_for_timeout(1000)
    _settle(page)
    got = _listed(page, hints=I['hints'])
    cards = got.get('cards') or got.get('names') or []
    assert cards, f"after '{I['label']}' no items are listed"
    word = I['word'].lower()
    other = [c.split('\n')[0] for c in cards if word not in c.lower()]
    for name, href in zip(got.get('names') or [], got.get('hrefs') or []):
        if name.split('\n')[0] in other and _mentions(page, href, I['word']):
            other.remove(name.split('\n')[0])
    assert not other, f"'{I['label']}' still shows items without '{I['word']}': {other[:3]}"
    _step_ok(f"all {len(cards)} item(s) shown say '{I['word']}'")


def _check_items_pages(page, I):
    page.goto(I['url'])
    _settle(page)
    one = set(_listed(page, hints=I['hints']).get('names') or [])
    nxt = page.locator(I['next']).first
    expect(nxt, 'the next-page control should be visible').to_be_visible()
    nxt.click()
    page.wait_for_timeout(1200)
    _settle(page)
    two = set(_listed(page, hints=I['hints']).get('names') or [])
    assert two, 'the next page lists no items'
    same = one & two
    assert not same or len(same) < len(two) / 2, f'the next page lists the same items: {sorted(same)[:4]}'
    _step_ok(f'the next page lists {len(two - one)} other item(s)')


def _check_items_smoke(page, console_errors, I):
    bad = []
    for url in I['urls']:
        errors_before = len(console_errors)
        resp = page.goto(url)
        _settle(page)
        broken = page.evaluate("[...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.src).map(i => i.src)")
        if resp is None or resp.status >= 400:
            bad.append(f"{url}: HTTP {resp.status if resp else '?'}")
        elif console_errors[errors_before:]:
            bad.append(f"{url}: JavaScript error {console_errors[errors_before][:100]}")
        elif broken:
            bad.append(f"{url}: broken picture {broken[0][-60:]}")
    assert not bad, f"{len(bad)} of {len(I['urls'])} page(s): " + '; '.join(bad[:4])
'''


def items_script(cases: list[dict], header: list[str]) -> str:
    out = ['"""Items in depth: the first, middle and last of each list open with their own name and price, a filter',
           'shows only matching items, the next page shows other items, more items of each kind open without errors."""',
           *header, ITEM_HELPERS, ""]
    for c in cases:
        kind = c["id"].rsplit("_", 1)[0].replace("items_", "")
        args = "page, console_errors" if kind == "smoke" else "page"
        out += (["@pytest.mark.guest  # a public page: tested as a visitor"] if c.get("guest") else []) + [
            f"def test_{c['id']}({args}):",
            f'    """{c["title"].replace(chr(34), chr(39)).replace(chr(92), "/")}"""',
            f"    I = {pformat(c['spec'], width=100, sort_dicts=False)}".replace("\n", "\n        "),
            f"    _check_items_{kind}({args}, I)", "", ""]
    return "\n".join(out).rstrip() + "\n"
