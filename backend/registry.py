"""The feature registry: every page and every feature the agent found, with a STABLE id, the evidence, and what
happened to it. Saved as runs/<run>/registry.json - the coverage numbers of the report come from here.

  pages     P-xxxxxxxx  one per address pattern (/product/{id} = one page with its samples and how many more exist)
  features  F-xxxxxxxx  three levels:
              control   one button / box / choice (with what exploring learned it does: its evidence)
              feature   search, filters, sorting, pages, add to cart, quantity, a form, a login ...
              workflow  a journey across pages (search -> product -> cart ...)
  edges     page -> page, by a link or by an action ("Add to compare" -> /compare)
  status    discovered -> inspected -> test generated -> tested -> verified, or: failed / blocked (protected) /
            needs a test account / inconclusive / clicked only (a click without a checked result proves nothing) /
            skipped / unresolved = not tested (+ why)
Discovered never counts as tested; tested never counts as verified unless a test checked the RESULT and passed.
A feature shared by many pages (the header's search box, a menu) is ONE feature of the site, tested once.
"""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urldefrag, urlparse

from .actions import PROTECTED, SEARCH_ICON

ID_SEGMENT = re.compile(r"^(\d+|[0-9a-f]{8,}|[0-9a-f-]{32,36}|[\w-]*\d[\w-]*)$", re.I)
LOGIN_WORDS = re.compile(r"log ?in|sign ?in|test account", re.I)


def _h(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:8].upper()


def page_pattern(p: dict) -> str:
    """'/product/12' -> '/product/{id}'; a single-page app route counts (#/offers). The query is NOT part of it:
    /shop?category=fruit and /shop?page=2 are states of /shop (kept as its samples), not other pages - except the
    part that picks the page on a website with one script for every page: index.php?rt=checkout/cart and
    ?rt=account/login are two pages (?rt=product/product&product_id=5 and =7 are one)."""
    from .agents.discovery import _query_route
    url, frag = urldefrag(p.get("url") or "")
    u = urlparse(url)
    path = u.path.rstrip("/") or "/"
    if frag.startswith(("/", "!/")):
        path += "#" + frag.lstrip("!")
    path = "/".join("{id}" if s and ID_SEGMENT.match(s) else s for s in path.split("/"))
    route = _query_route(u.query)
    return path + ("?" + "&".join(route) if route else "")


def page_id(p: dict) -> str:
    return "P-" + _h(f"{bool(p.get('auth'))}|{page_pattern(p)}")


def feature_id(where: str, kind: str, key: str) -> str:
    return "F-" + _h(f"{where}|{kind}|{key}")


def _control_key(x: dict) -> str:
    return f"{(x.get('accname') or x.get('text') or x.get('label') or '').strip()[:60]}|{x.get('selector')}"


def _hovers(p: dict) -> list[dict]:
    """The page's hover menus as controls (named by their steady words: the cart menu's '2 ITEMS - $59.00' -> 'ITEMS')."""
    return [{"text": h.get("name") or h.get("text") or "menu", "selector": h["selector"], "kind": "hover", "role": "menu"}
            for h in p.get("hovers") or [] if h.get("selector")]


SHARED_KINDS = {"search", "suggestions", "login"}  # page features that are one control on every page (the header's)


def build(app_map: list[dict], crawl: dict) -> dict:
    """The registry right after exploring: every page and feature discovered and inspected (nothing tested yet)."""
    from .actions import action_risk
    from .agents.test_design import features as basic_features
    from .auth import login_form
    from .features import page_features

    pages, features, edges, by_url = {}, {}, [], {}
    seen_on = Counter()  # control key -> on how many page patterns (shared header / footer controls: one feature)
    pattern_controls: dict[str, set] = {}
    for p in app_map:
        pattern_controls.setdefault(page_id(p), set()).update(
            _control_key(x) for x in p.get("buttons", []) + p.get("inputs", []) + _hovers(p))
    for keys in pattern_controls.values():
        for k in keys:
            seen_on[k] += 1
    shared = {x.get("selector") for p in app_map for x in p.get("buttons", []) + p.get("inputs", []) + _hovers(p)
              if x.get("selector") and seen_on[_control_key(x)] > 1}
    sampled = Counter()
    for s in crawl.get("skipped", []):
        m = re.search(r"address pattern \(([^)]+)\)", s.get("reason", ""))
        if m:
            sampled[m.group(1)] += 1

    def add(f: dict) -> str:
        fid = f["id"]
        if fid in features:
            old = features[fid]
            old["pages"] = sorted(set(old["pages"]) | set(f["pages"]))
            if f.get("hrefs"):
                old["hrefs"] = list(dict.fromkeys((old.get("hrefs") or []) + f["hrefs"]))
            if f.get("evidence") and not old.get("evidence"):
                old["evidence"] = f["evidence"]
        else:
            features[fid] = dict({"status": "inspected", "why": "", "tests": [], "outcomes": {}}, **f)
        return fid

    for p in app_map:
        pid = page_id(p)
        by_url[(p.get("url"), bool(p.get("auth")))] = pid
        pg = pages.setdefault(pid, {
            "id": pid, "pattern": page_pattern(p), "auth": bool(p.get("auth")), "type": p.get("page_type") or "content",
            "urls": [], "slugs": [], "status": p.get("status"), "needs_permission": bool(p.get("needs_permission")),
            "error": p.get("error") or "", "lazy": bool(p.get("lazy")), "features": [], "state": "discovered"})
        pg["urls"].append(p.get("url"))
        pg["slugs"].append(p.get("slug"))
        # (an API address the crawl opened from a link answers 405: its error page - 'Media type', 'Content', 'OPTIONS'
        # on automationexercise.com/api/createAccount - is no feature of the website)
        if p.get("error") or p.get("needs_permission") or p.get("status") == 405:
            continue
        pg["state"] = "inspected"
        slug, auth = p.get("slug"), bool(p.get("auth"))
        learned = {(b.get("control"), b.get("selector")): b for b in p.get("behaviour", [])}
        by_sel = {b.get("selector"): b for b in p.get("behaviour", [])}
        basic = basic_features(p)
        # the search box's own button(s) - also one that only shows a magnifier: the search tests use the box (Enter,
        # then its button when Enter does nothing), so they test these too
        search_buttons = [b["selector"] for b in p.get("buttons", []) if basic["search"] and b.get("selector")
                          and (re.fullmatch(r"\s*search\s*", b.get("text") or "", re.I)
                               or (SEARCH_ICON.search(b.get("text") or "") and not PROTECTED.search(b.get("text") or "")))]
        # features: what the inspector found (search, filters, sorting ...) - with every control a test of it uses
        for f in page_features(p):
            if f["kind"] == "protected":
                for a in f["actions"]:
                    pg["features"].append(add({"id": feature_id(pid, "protected", a["text"].lower()), "level": "feature",
                                               "kind": "protected", "name": a["text"], "page": pid, "pages": [slug],
                                               "auth": auth, "selector": a.get("selector"), "risk": "protected",
                                               "status": "blocked", "why": "protected action: never performed without "
                                               "explicit approval in a test environment"}))
                continue
            uses = [f.get("selector")] + list(f.get("boxes") or []) + [l.get("selector") for l in f.get("links") or []]
            uses += search_buttons if f["kind"] == "search" else []
            where = "site" if f["kind"] in SHARED_KINDS and f.get("selector") in shared else pid
            hrefs = [l["href"] for l in (p.get("itemLinks") or {}).get("links") or [] if l.get("href")] \
                if f["kind"] == "items" else []  # (its items' links: their own link tests judge the list)
            pg["features"].append(add({"id": feature_id(where, f["kind"], ""), "level": "feature", "kind": f["kind"],
                                       "name": f.get("name") or f["kind"], "page": where, "pages": [slug], "auth": auth,
                                       "selector": f.get("selector"), "uses": sorted({u for u in uses if u}),
                                       "evidence": by_sel.get(f.get("selector")), **({"hrefs": hrefs} if hrefs else {})}))
        from .agents.test_design import _quantity_box
        qbox = basic["qty"] or (_quantity_box(p) if basic["add"] else "")  # (+ / - buttons, or a quantity box)
        if qbox:
            pg["features"].append(add({"id": feature_id(pid, "quantity", ""), "level": "feature", "kind": "quantity",
                                       "name": "quantity - / +" if basic["qty"] else "quantity", "page": pid,
                                       "pages": [slug], "auth": auth, "selector": qbox,
                                       "uses": [x for x in (qbox, basic["plus"], basic["minus"]) if x]}))
        lf = login_form(p) if not auth else None
        if lf:  # the login (its tests: wrong password refused, the test account works, the login journey)
            where = "site" if lf["user"] in shared else pid
            pg["features"].append(add({"id": feature_id(where, "login", ""), "level": "feature", "kind": "login",
                                       "name": "login form", "page": where, "pages": [slug], "auth": auth,
                                       "selector": lf["user"], "uses": [lf["user"], lf["password"], lf["submit"]]}))
        for fm in p.get("forms", []):
            fields = {x.get("selector") for x in fm.get("fields", [])}
            if basic["search"] and basic["search"] in fields:
                continue  # (the search form IS the search feature)
            if lf and lf["submit"] == (fm.get("submit") or {}).get("selector"):
                continue  # (the login form IS the login feature)
            name = ((fm.get("submit") or {}).get("text") or "form").strip()[:40]
            sends = action_risk(name, (fm.get("submit") or {}).get("selector")) == "protected"
            pg["features"].append(add(dict({"id": feature_id(pid, "form", fm.get("selector") or name),
                                            "level": "feature", "kind": "form", "name": f"form '{name}'", "page": pid,
                                            "pages": [slug], "auth": auth, "selector": fm.get("selector"),
                                            "uses": [(fm.get("submit") or {}).get("selector")]},
                                           **({"status": "blocked", "why": f"sending it ('{name}') is a protected "
                                               "action: never done without explicit approval"} if sends else {}))))
        # controls: every button / box / choice / hover menu, with what exploring learned it does
        for x in p.get("buttons", []) + p.get("inputs", []) + _hovers(p):
            if not x.get("selector") or (x.get("type") or "") in ("hidden",):
                continue
            key = _control_key(x)
            where = "site" if seen_on[key] > 1 else pid  # on several pages: ONE shared control
            ev = learned.get(((x.get("accname") or x.get("text") or x.get("label") or "").strip()[:60], x["selector"])) \
                or next((b for b in p.get("behaviour", []) if b.get("selector") == x["selector"]), None)
            name = (x.get("accname") or x.get("text") or x.get("label") or "control").split("\n")[0].strip()[:60]
            extra = {}
            if x in p.get("buttons", []) and action_risk(x.get("text") or name, x["selector"]) == "protected":
                extra = {"status": "blocked", "why": "protected action: never performed without explicit approval in "
                                                     "a test environment"}
            pg["features"].append(add(dict({
                "id": feature_id(where, "control", key), "level": "control",
                "kind": x.get("kind") or x.get("role") or x.get("tag") or "control",
                "name": name, "page": where, "pages": [slug], "auth": auth, "selector": x["selector"],
                "role": x.get("role") or "", "submit": (x.get("type") or "").lower() == "submit" and bool(x.get("in_form")),
                "revealed_by": x.get("revealed_by_name") or x.get("revealed_by"), "evidence": ev,
                "frame": x.get("frame", ""), "shadow": " > ".join(x.get("shadow_path") or [])}, **extra)))
        # edges: links and actions that lead to other pages
        for l in p.get("links", []):
            if not l.get("external"):
                edges.append({"from": pid, "to_url": l["href"], "via": "link", "label": (l.get("text") or "")[:40]})
        for b in p.get("behaviour", []):
            if b.get("to"):
                edges.append({"from": pid, "to_url": b["to"], "via": "action", "label": b.get("control")})
    for pg in pages.values():
        pg["features"] = sorted(set(pg["features"]))
        pg["sampled_out"] = sampled.get(pg["pattern"].split("?")[0], 0)
    url_pid = {u: pid for (u, _a), pid in by_url.items()}
    for e in edges:
        e["to"] = url_pid.get(e["to_url"].split("#")[0].rstrip("/")) or url_pid.get(e["to_url"])
    edges = [e for e in edges if e["to"] and e["to"] != e["from"]]
    unique = {(e["from"], e["to"], e["via"]): e for e in edges}
    return {"pages": pages, "features": features, "edges": list(unique.values()), "counts": {}}


# ---------------------------------------------------------------- tests -> features
def _index(reg: dict) -> dict:
    idx = {}
    slug_pid = {s: pid for pid, pg in reg["pages"].items() for s in pg["slugs"]}
    for fid, f in reg["features"].items():
        for slug in f["pages"]:
            if f.get("selector"):
                idx.setdefault(("sel", slug, f["selector"]), fid)
            idx.setdefault(("kind", slug, f["kind"]), fid)
            if f["kind"] == "protected":
                idx.setdefault(("protected", slug, f["name"].lower()), fid)
            if f["level"] == "control":
                idx.setdefault(("controls", slug), []).append(fid)
                if f.get("selector"):
                    idx.setdefault(("ctl", slug, f["selector"]), fid)
        if f.get("selector"):
            idx.setdefault(("sel", None, f["selector"]), fid)
            if f["level"] == "control":
                idx.setdefault(("ctl", None, f["selector"]), fid)
    idx["_slug_pid"] = slug_pid
    idx["_features"] = reg["features"]
    return idx


STEP_KIND = {"search_finds_item": "search", "search_no_results": "search", "add_to_cart": "add_to_cart",
             "quantity_plus_minus": "quantity"}


def _step_links(step: dict, slug: str, idx: dict) -> list[tuple[str, str]]:
    """(feature id, 'verifies' | 'clicks') for one step of a large case."""
    out = []
    sid = step.get("id", "")
    if sid == "buttons_click":  # click each button, no checked result: a click proves nothing
        return [(f, "clicks") for f in idx.get(("controls", slug), [])]
    kind = STEP_KIND.get(sid) or {"login_wrong": "login", "login_ok": "login"}.get(step.get("kind")) \
        or ("suggestions" if step.get("kind") == "opens" and step.get("typing") else "") \
        or ("form" if sid.endswith(("_required_validation", "_invalid_email")) else "")
    if kind:
        fid = idx.get(("kind", slug, kind))
        if fid:
            out.append((fid, "verifies"))
    for s in [step.get("selector")] + list(step.get("tabs") or []) + list(step.get("radios") or []):
        fid = _control(idx, slug, s) if s else None
        if fid:
            out.append((fid, "verifies"))
    return out


def _control(idx: dict, slug, sel: str):
    """The control with this selector on this page (or the shared one), else whatever feature has it."""
    return idx.get(("ctl", slug, sel)) or idx.get(("ctl", None, sel)) or idx.get(("sel", slug, sel)) \
        or idx.get(("sel", None, sel))


def own_tests(c: dict, idx: dict) -> dict[str, list[str]]:
    """{feature id: its single tests ('file::test')} in a site-wide case: the values typed into ONE box, the links of
    ONE list's items. A feature is judged by these - never by a failing check of another page."""
    from .agents.script_generator import _ident, link_test_id
    own: dict[str, list[str]] = {}
    if c.get("id") == "site_input_values":
        for d in c.get("checks") or []:
            fid = _control(idx, d.get("page"), d.get("selector"))
            if fid:
                own.setdefault(fid, []).append(f"test_{_ident(d['page'])}_data.py::test_{_ident(d['id'])}")
    elif c.get("id") == "site_links":
        for fid, f in idx["_features"].items():
            if f["level"] == "feature" and f["kind"] in ("items", "order_link") and f.get("hrefs"):
                own[fid] = [f"test_all_links.py::test_link[{link_test_id(h.split('#')[0], False)}]" for h in f["hrefs"]]
    return own


def case_links(c: dict, idx: dict) -> list[tuple[str, str]]:
    """Which features a test case tests, and how ('verifies' = it checks a result, 'clicks' = it only clicks)."""
    out = []
    slugs = c.get("pages") or [s.strip() for s in str(c.get("page", "")).split(",") if s.strip()]
    if c.get("feature_ids"):  # (cases made from learned evidence carry their feature ids)
        out += [(f, "verifies") for f in c["feature_ids"]]
    for part in c.get("parts") or []:
        out += _step_links(part["step"], part["page"], idx)
    if c.get("kind") == "feature":
        for slug in slugs:
            fid = idx.get(("kind", slug, {"filter_pages": "pagination"}.get(c.get("feature_kind"), c.get("feature_kind"))))
            if fid:
                out.append((fid, "verifies"))
    if c.get("kind") == "learned":  # the control whose learned effect it checks
        sel = (c.get("spec") or {}).get("selector")
        for slug in slugs:
            fid = _control(idx, slug, sel)
            if fid:
                out.append((fid, "verifies"))
    if c.get("blocked"):
        name = (c.get("title") or "").split("'")[1].lower() if "'" in (c.get("title") or "") else ""
        for slug in slugs:
            fid = idx.get(("protected", slug, name))
            if fid:
                out.append((fid, "blocked"))
    if c.get("journey"):  # a journey USES these features: when it passes, every step of it was verified (evidence for
        # them); when it fails, it fails as the workflow it is - never every feature it went through (their own tests)
        for kind in {"login": ["login"], "shop": ["search", "add_to_cart"], "product": ["items", "add_to_cart", "option"],
                     "orders": ["order_link"], "form": ["form"], "cart": ["quantity"]}.get(c["journey"], []):
            for slug in slugs:
                fid = idx.get(("kind", slug, kind))
                if fid:
                    out.append((fid, "uses"))
    if c.get("id") in ("site_input_values", "site_links"):  # (each box / list: by its OWN single tests - own_tests)
        out += [(fid, "verifies") for fid in own_tests(c, idx)]
    if c.get("kind") in ("form", "crud", "pair"):  # a form test: the form feature, and the box(es) whose rule it checks
        s = c.get("spec") or {}
        for slug in slugs[:1]:
            fid = idx.get(("sel", slug, s.get("form"))) or idx.get(("kind", slug, "form"))
            if fid:
                out.append((fid, "verifies"))
            for box in [s.get("box")] + list(s.get("pair") or []):
                cfid = _control(idx, slug, box) if box else None
                if cfid:
                    out.append((cfid, "verifies"))
    # a test of a feature also tests the controls it uses (its +/- buttons, its filter boxes, its submit button)
    for fid, how in list(out):
        f = idx["_features"].get(fid) or {}
        for sel in f.get("uses") or []:
            for slug in f.get("pages") or []:
                cfid = idx.get(("ctl", slug, sel)) or idx.get(("ctl", None, sel))
                if cfid and cfid != fid:
                    out.append((cfid, how))
    return list(dict.fromkeys(out))


def link_tests(reg: dict, cases: list[dict]) -> None:
    """Attach every test case to the features it tests (and workflows to themselves)."""
    idx = _index(reg)
    for c in cases:
        if c.get("journey"):  # a workflow is a feature of its own
            fid = feature_id("site", "workflow", c.get("tc_id") or c.get("title", ""))
            reg["features"].setdefault(fid, {"id": fid, "level": "workflow", "kind": c["journey"], "name": c["title"],
                                             "page": "site", "pages": c.get("pages") or [], "auth": not c.get("guest"),
                                             "status": "inspected", "why": "", "tests": [], "outcomes": {}})
            c.setdefault("feature_ids", [])
            if fid not in c["feature_ids"]:
                c["feature_ids"].append(fid)
        links = case_links(c, idx)
        c["linked_features"] = [f for f, _ in links]
        if not c.get("feature_ids"):  # (the features whose result this case checks - else the ones it uses: its IDs)
            c["feature_ids"] = [f for f, how in links if how == "verifies"] or [f for f, _ in links]
        own = own_tests(c, idx) if c.get("id") in SITE_WIDE else None
        for fid, how in links:
            f = reg["features"].get(fid)
            if f is None or (own is not None and fid not in own):
                continue  # (a site-wide case tests a feature only through the single tests of its own)
            if c.get("tc_id") not in [t["tc_id"] for t in f["tests"]]:
                f["tests"].append(dict({"tc_id": c.get("tc_id"), "how": how}, **({"own": own[fid]} if own else {})))


SITE_WIDE = ("site_input_values", "site_links")  # one case, many single tests: each feature is judged by its own
# a failure that only says the test could not reach the feature (element not found, timeout, network, test data) is
# no evidence that the feature is broken: such a feature is INCONCLUSIVE, never failed
NOT_PROVEN = {"locator", "test_defect", "infrastructure", "timeout", "test_data", "auth_problem", "test_mistake"}


def _own_status(keys: list[str], by_key: dict) -> tuple | None:
    """(status, why, failing results, assertions) of a feature's own single tests - None = none of them ran."""
    rs = [by_key[k] for k in keys if k in by_key]
    if not rs:
        return None
    bad = [r for r in rs if r.get("outcome") in ("failed", "error") and not r.get("flaky")]  # (flaky: passed on a retry)
    checks = sum(int(r.get("checks") or 0) for r in rs)
    if bad:
        return "Failed", (bad[0].get("error") or "").strip().split("\n")[-1][:200], bad, checks
    if any(r.get("outcome") == "inconclusive" for r in rs):
        return "Inconclusive", "", [], checks
    if all(r.get("outcome") == "skipped" for r in rs):
        return "Skipped", (rs[0].get("error") or "")[:200], [], checks
    return ("Flaky" if any(r.get("flaky") for r in rs) else "Passed"), "", [], checks


def decided(f: dict, by_tc: dict, results: list[dict] | None, strength: dict | None = None) -> list[dict]:
    """What decides a feature's status: each linked test case's result FOR THIS FEATURE (a site-wide case: its own
    single tests), why, the failure classes of its failing tests, how many assertions ran, and whether a passed test
    checked a state / value (strong) or only that nothing broke (weak - backend/assert_strength.py)."""
    from .agents.failure_analysis import classify
    from .assert_strength import of_result
    from .excel import case_hits
    by_key = {f"{r.get('file')}::{r.get('test')}": r for r in results or []}
    out = []
    for t in f["tests"]:
        c = by_tc.get(t["tc_id"])
        if c is None:
            continue
        if t.get("own") is not None and results is not None:
            own = _own_status(t["own"], by_key)
            if own is None:
                continue  # (none of its own checks ran)
            status, why, bad, checks = own
            ran = [by_key[k] for k in t["own"] if k in by_key]
        else:
            hits = case_hits(c, results) if results is not None else []
            status, why = c.get("execution_status"), c.get("actual_result") or ""
            bad = [r for r in hits if r.get("outcome") in ("failed", "error") and not r.get("flaky")]
            checks = sum(int(r.get("checks") or 0) for r in hits) if results is not None else None
            ran = hits
        strong = not strength or any(of_result(r, strength) == "strong" for r in ran
                                     if r.get("outcome") == "passed" or r.get("flaky"))
        if c.get("journey") == "form" or c.get("verification_level") == "input_only":
            strong = False
        out.append({"tc_id": t["tc_id"], "how": t["how"], "status": status, "why": why, "checks": checks,
                    "kinds": sorted({classify(r)[0] for r in bad}), "title": c.get("title", ""), "strong": strong})
    return out


SMOKE = re.compile(r"^test_(page_opens|no_console_errors|images_load)\[(.+)\]$")


def page_checks(results: list[dict] | None) -> dict:
    """{page slug: did its own page checks pass?} - opens, no JavaScript errors, pictures load (test_site.py)."""
    out = {}
    for r in results or []:
        m = SMOKE.match(r.get("test") or "")
        if m and r.get("outcome") != "skipped":
            out[m.group(2)] = out.get(m.group(2), True) and r.get("outcome") == "passed"
    return out


def record_outcomes(reg: dict, cases: list[dict], crawl: dict | None = None, results: list[dict] | None = None,
                    strength: dict | None = None) -> dict:
    """After the run: each feature's status from its tests' results (+ why when it is not verified), and the counts.
    `results` (the single test results) add each page's own checks (opens, no JavaScript errors, pictures).
    `strength` (strength.json): a feature whose passed tests only checked that nothing broke is 'smoke', not verified."""
    from .agents.test_design import CART_STATE
    reg["page_checks"] = page_checks(results) if results is not None else reg.get("page_checks", {})
    by_tc = {c.get("tc_id"): c for c in cases}
    for f in reg["features"].values():
        if f["status"] in ("blocked", "unsupported"):
            continue
        linked = decided(f, by_tc, results, strength)
        f["decided_by"] = linked
        f["outcomes"] = {x["tc_id"]: x["status"] for x in linked}
        # a journey that USES the feature counts when it passed (each of its steps was verified); its failure is the
        # workflow's - the feature's own tests decide (one failing step never fails every feature on the way)
        checked = [x for x in linked if x["how"] == "verifies" or (x["how"] == "uses" and x["status"] in ("Passed", "Flaky"))]
        st = [x["status"] for x in checked]
        failing = [x for x in checked if x["status"] == "Failed"]
        questions = {"rule_violation", "suspect"}  # (a convention not kept / a control that did nothing: ask a person)
        proven = [x for x in failing if not (x["kinds"] and set(x["kinds"]) <= NOT_PROVEN | questions)]
        rule = next((x for x in failing if x["kinds"] and set(x["kinds"]) <= {"rule_violation"}), None)
        suspect = next((x for x in failing if x["kinds"] and set(x["kinds"]) <= {"suspect"}), None)
        if proven:
            f["status"], f["why"] = "failed", (proven[0]["why"] or "")[:200]
        elif rule:
            f["status"], f["why"] = "rule_violation", (rule["why"] or "a rule between fields was not kept")[:200]
        elif suspect:
            f["status"], f["why"] = "suspect", "it did nothing - while exploring and in its test (needs a person to look)"
        elif ("Passed" in st or "Flaky" in st) and not any(x["strong"] for x in checked
                                                           if x["status"] in ("Passed", "Flaky")):
            f["status"], f["why"] = "smoke", "its passed test only checked that nothing broke (no errors) - not that it works"
        elif "Passed" in st or "Flaky" in st:
            f["status"], f["why"] = "verified", "flaky: passed on a retry" if "Passed" not in st else ""
        elif failing:  # its test could not reach it: no evidence that it is broken
            f["status"], f["why"] = "inconclusive", (f"its test could not check it ({', '.join(failing[0]['kinds'])} "
                                                     f"problem, not a website defect): {failing[0]['why'][:150]}")
        elif st and all(s == "Skipped" for s in st) and any(LOGIN_WORDS.search(f"{x['why']} {by_tc[x['tc_id']].get('skip_reason')}")
                                                            for x in checked):
            f["status"], f["why"] = "needs_login", "needs a test account (the website asks a visitor to sign in)"
        elif "Inconclusive" in st:
            f["status"], f["why"] = "inconclusive", "the test ran but could not establish the expected result"
        elif any(s == "Blocked" for s in st):
            f["status"], f["why"] = "blocked", "its test reached a protected action"
        elif st and all(s == "Skipped" for s in st):
            f["status"], f["why"] = "skipped", next((x["why"] or by_tc[x["tc_id"]].get("skip_reason") or "")
                                                     for x in checked)[:200]
        elif any(x["how"] == "uses" and x["status"] in ("Failed", "Flaky") for x in linked):
            j = next(x for x in linked if x["how"] == "uses" and x["status"] in ("Failed", "Flaky"))
            f["status"], f["why"] = "inconclusive", (f"only used inside the journey '{j['title'][:60]}', which "
                                                     f"failed: {(j['why'] or '')[:120]}")
        elif linked:  # only clicked (no checked result) - or its test did not run
            ran = [x for x in linked if x["status"] not in ("Not run", "Pending", None)]
            f["status"], f["why"] = (("clicked_only", "only clicked: no result was checked") if ran else
                                     ("test_generated", "a test case was written for it, but it did not run "
                                                        "(time limit, MAX_TEST_CASES, or its script was rejected)"))
        else:
            ev = f.get("evidence") or {}
            if ev.get("effect") == "nothing":  # tried, but nothing observable: no evidence either way
                f["status"], f["why"] = "inconclusive", (
                    "using it showed nothing visible while exploring (e.g. a link to this very page, a slider "
                    "arrow, 'Previous' on the first page) - there is no observable result to test")
            elif (reg["pages"].get(f.get("page")) or {}).get("type") == "cart":
                f["status"], f["why"] = "unresolved", CART_STATE
            else:
                f["status"], f["why"] = "unresolved", ("learning it failed: " + ev.get("error", "")
                                                       if ev.get("effect") == "error" else "no test was generated for it")
    reg["counts"] = counts(reg, crawl)
    return reg


STATUS_TEXT = {  # the status of a feature in words (report, Excel, chat)
    "verified": "verified", "failed": "failed", "blocked": "blocked (protected)", "inconclusive": "inconclusive",
    "clicked_only": "tested - only clicked, no result checked", "needs_login": "not tested - needs a test account",
    "skipped": "not tested - skipped", "test_generated": "test generated - it did not run",
    "unresolved": "not tested", "inspected": "inspected", "discovered": "discovered",
    "smoke": "smoke only - it did not break, but nothing proves it works",
    "suspect": "suspect - it did nothing, while exploring and in its test (needs a person to look)",
    "rule_violation": "rule violation? - it broke a common convention (a question for you)",
    "unsupported": "unsupported - its content can't be read (a closed shadow root)"}


def _page_why(pg: dict, here: list[dict], own: list[bool]) -> str:
    """Why a page is not verified (one sentence)."""
    if pg["state"] == "verified":
        return ""
    if pg.get("needs_permission"):
        return "needs other permissions (this account may not open it)"
    if pg.get("error"):
        return f"could not be opened: {str(pg['error'])[:120]}"
    if own and not all(own):
        return "its own page checks failed (opens / no JavaScript errors / pictures load)"
    bad = [f for f in here if f["status"] == "failed"]
    if bad:
        return f"{len(bad)} feature(s) failed: " + ", ".join(f["name"] for f in bad[:4])
    unclear = [f for f in here if f["tests"] and f["status"] in ("inconclusive", "clicked_only")]
    if unclear:
        return ("not proven: " + ", ".join(f"{f['name']} ({STATUS_TEXT[f['status']]})" for f in unclear[:3]))
    if pg["state"] == "discovered":
        return "found, but it was not opened"
    return "no test ran on it - each of its features says why"


def counts(reg: dict, crawl: dict | None = None) -> dict:
    fs = list(reg["features"].values())
    by = Counter(f["status"] for f in fs)
    tested = {"verified", "failed", "needs_login", "inconclusive", "skipped", "clicked_only", "smoke", "suspect",
              "rule_violation"}
    pages = list(reg["pages"].values())
    checks = reg.get("page_checks") or {}
    ident = lambda s: re.sub(r"[^a-zA-Z0-9_]+", "_", s or "").strip("_").lower()  # noqa: E731  (pytest ids)
    for pg in pages:
        # tested: one of its OWN features was (a site-wide one - the header's search - is counted once, as a feature),
        # or its own page checks ran (opens, no JavaScript errors, pictures); verified: its page checks passed, none
        # of its features failed, and what was tested was verified. Not verified -> why.
        here = [reg["features"][f] for f in pg["features"] if f in reg["features"]
                and reg["features"][f].get("page") == pg["id"]]
        st = [x["status"] for x in here if x["tests"]]  # (only tried while exploring, nothing to test: not counted)
        own = [checks[ident(s)] for s in pg["slugs"] if ident(s) in checks]
        if pg["state"] in ("inspected", "tested", "verified") and (any(s in tested for s in st) or own):
            ok = all(own) and not any(s in ("failed", "inconclusive", "clicked_only") for s in st)
            ok = ok and (any(s == "verified" for s in st) or not any(s in tested for s in st))
            pg["state"] = "verified" if ok else "tested"
        pg["why"] = _page_why(pg, here, own)
    ps = Counter(pg["state"] for pg in pages)
    return {
        "pages": {"discovered": len(pages), "inspected": sum(ps[s] for s in ("inspected", "tested", "verified")),
                  "tested": ps["tested"] + ps["verified"], "verified": ps["verified"],
                  "needs_permission": sum(1 for pg in pages if pg["needs_permission"]),
                  "failed_to_open": sum(1 for pg in pages if pg["error"]),
                  "sampled_out": sum(pg.get("sampled_out", 0) for pg in pages),
                  "not_reached": (crawl or {}).get("not_visited_count", 0)},
        "features": {"discovered": len(fs), "tested": sum(1 for f in fs if f["status"] in tested and f["tests"]),
                     # the life of a feature: found -> read on its page -> a test written -> a test ran -> verified
                     "lifecycle": {"discovered": len(fs), "inspected": sum(1 for f in fs if f["status"] != "discovered"),
                                   "test_generated": sum(1 for f in fs if f["tests"] and f["status"] != "blocked"),
                                   "tested": sum(1 for f in fs if f["status"] in tested and f["tests"]),
                                   "verified": by["verified"]},
                     "verified": by["verified"], "test_generated": by["test_generated"],
                     "failed": by["failed"], "blocked": by["blocked"], "needs_login": by["needs_login"],
                     "inconclusive": by["inconclusive"], "clicked_only": by["clicked_only"], "skipped": by["skipped"],
                     "unresolved": by["unresolved"], "smoke": by["smoke"], "suspect": by["suspect"],
                     "rule_violation": by["rule_violation"], "unsupported": by["unsupported"],
                     "by_level": {lvl: {"discovered": sum(1 for f in fs if f["level"] == lvl),
                                        "verified": sum(1 for f in fs if f["level"] == lvl and f["status"] == "verified")}
                                  for lvl in ("control", "feature", "workflow")}},
        "denominator": "every page pattern and every feature found on the pages that were reached (sampled pages of "
                       "one pattern count once; pages not reached are listed, not counted)",
    }


def save(reg: dict, run_dir) -> None:
    Path(run_dir, "registry.json").write_text(json.dumps(reg, indent=2), encoding="utf-8")


def load(run_dir) -> dict | None:
    try:
        return json.loads(Path(run_dir, "registry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
