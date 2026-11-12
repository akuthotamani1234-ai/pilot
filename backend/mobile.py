"""Phone width (Step 16): the controls a page shows only at 390 x 844 (a hamburger menu, mobile filters) are tested
at that size - each must be visible there and change something when used. Layout problems at phone width (sideways
scroll, controls cut off or covered) are findings of the crawl (discovery LAYOUT_JS), not tests.
"""
from pprint import pformat
from urllib.parse import urlparse

PHONE = {"width": 390, "height": 844}


def mobile_cases(pages: list[dict]) -> list[dict]:
    out, seen = [], set()
    for p in pages:
        for b in p.get("mobile_only") or []:
            key = (b.get("text"), b.get("selector"))
            if key in seen or len(out) >= 20:
                continue
            seen.add(key)
            name = (b.get("text") or b.get("accname") or "control").split("\n")[0].strip()[:40] or "control"
            n = len(out) + 1
            out.append({"id": f"mobile_{n}", "kind": "mobile", "type": "positive", "priority": "medium",
                        "title": f"Phone width: '{name}' (only on a phone) works ({urlparse(p['url']).path or '/'})",
                        "steps": ["Open the page on a phone-sized screen (390 x 844)", f"Use '{name}'"],
                        "expected": "It is shown at phone width and opens / changes something when used",
                        "page": p["slug"], "url": p["url"], "pages": [p["slug"]], "guest": not p.get("auth"),
                        "test_data": "390 x 844", "files": ["test_mobile.py"], "tests": [f"test_mobile_{n}"],
                        "spec": {"url": p["url"], "selector": b["selector"], "name": name, "width": PHONE["width"]}})
    return out


MOBILE_HELPERS = r'''
COUNT_SHOWN_JS = "() => [...document.querySelectorAll('a, button, input')].filter(e => e.offsetParent !== null).length"


def _check_mobile(page, M):
    page.set_viewport_size({'width': 390, 'height': 844})
    try:  # (the browser tab is shared by the tests: the desktop size always comes back)
        page.goto(M['url'])
        _settle(page)
        el = page.locator(M['selector']).first
        expect(el, f"'{M['name']}' should be shown at phone width").to_be_visible()
        before, shown = page.locator('body').inner_text(), page.evaluate(COUNT_SHOWN_JS)
        el.click(timeout=5000)
        page.wait_for_timeout(900)
        after, now = page.locator('body').inner_text(), page.evaluate(COUNT_SHOWN_JS)
        assert after != before or now != shown or page.url != M['url'], f"'{M['name']}' changed nothing at phone width"
        _step_ok(f"'{M['name']}' works at phone width ({shown} -> {now} controls shown)")
    finally:
        page.set_viewport_size({'width': 1366, 'height': 900})
'''


def mobile_script(cases: list[dict], header: list[str]) -> str:
    out = ['"""Phone width (390 x 844): the controls only a phone shows - a hamburger menu, mobile filters - work."""',
           *header, MOBILE_HELPERS, ""]
    for c in cases:
        out += (["@pytest.mark.guest  # a public page: tested as a visitor"] if c.get("guest") else []) + [
            f"def test_{c['id']}(page):", f'    """{c["title"].replace(chr(34), chr(39))}"""',
            f"    M = {pformat(c['spec'], width=100, sort_dicts=False)}", "    _check_mobile(page, M)", "", ""]
    return "\n".join(out).rstrip() + "\n"
