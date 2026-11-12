"""How accurate was a test run? Measured from the run's own files, honestly.

With a KNOWN-TRUTH manifest (a practice website whose pages, features and planted bugs are known, e.g.
tests/demo_store_truth.json) it says what the agent found and what it missed:
  pages     known pages discovered (missing ones listed); a 403 page recorded as "needs permission"
  features  known features detected (seen on the page) / tested (a test about it ran) / verified (a test that really
            checks its result passed) / correct (the right outcome: verified, blocked = protected, needs a test account)
  bugs      planted bugs caught (their test failed) / missed (their test passed = a FALSE PASS, or no test at all)
  alarms    failed tests that are not about a planted bug (FALSE ALARMS)
  safety    requests that must never happen (place order, buy now, log out ...)
Without a manifest (a real website, whose full feature list nobody knows) only the run's own counts are given.

    python -m backend.accuracy runs/<run> [--truth tests/demo_store_truth.json] [--bugs]
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

RAN = ("Passed", "Failed", "Flaky", "Skipped", "Inconclusive")
# query parts that never pick the page (tracking, display settings, sessions)
NOT_THE_PAGE = re.compile(r"^(utm_\w+|gclid|fbclid|msclkid|_ga|_gl|currency|language|lang|locale|sid|phpsessid|"
                          r"jsessionid)$", re.I)
# "click it, no error" is no proof that a feature works: such steps don't count as testing the feature
CLICK_ONLY = re.compile(r"^every button can be clicked|click each button", re.I)
LOGIN_NEEDED = re.compile(r"log ?in|sign ?in|test account", re.I)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _rx(pattern: str) -> re.Pattern:
    """'/product/{id}' -> ^/product/[^/]+/?$"""
    return re.compile("^" + re.escape(pattern).replace(re.escape("{id}"), "[^/]+") + "/?$")


def _path(page_or_url) -> str:
    """Where a page is: its path, and its query without tracking / display settings ('/index.php?rt=checkout%2Fcart')."""
    url = page_or_url if isinstance(page_or_url, str) else (page_or_url.get("final_url") or page_or_url.get("url"))
    u = urlparse(url or "")
    q = sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not NOT_THE_PAGE.match(k))
    return (u.path.rstrip("/") or "/") + ("?" + urlencode(q) if q else "")


def _matches(pattern: str, where: str) -> bool:
    """Is the page at `where` (see _path) one of the truth's page `pattern`? '/product/{id}' compares the path;
    '/index.php?rt=product/product&product_id={id}' also these query values ({id} = any; others are ignored).
    A path pattern never matches a page that a query route picks ('/' is not '/?rt=checkout/cart')."""
    from .agents.discovery import _query_route
    ppath, _, pq = pattern.partition("?")
    path, _, q = where.partition("?")
    if not _rx(ppath).match(path):
        return False
    if not pq:
        return not _query_route(q)
    got = dict(parse_qsl(q, keep_blank_values=True))
    return all(k in got and (v == "{id}" or got[k] == v) for k, v in parse_qsl(pq, keep_blank_values=True))


def _evidence(p: dict) -> str:
    """Everything the agent recorded about a page, as one lower-case text."""
    bits = [p.get("title") or "", p.get("page_type") or "", " ".join(map(str, p.get("features") or []))]
    bits += [f"{b.get('text')} {b.get('name') or ''} {b.get('selector')}" for b in p.get("buttons", [])]
    bits += [f"{i.get('label')} {i.get('name')} {i.get('placeholder')} {i.get('selector')}" for i in p.get("inputs", [])]
    bits += [l.get("text") or "" for l in p.get("links", [])]
    bits += list(p.get("headings") or []) + list(p.get("itemNames") or [])
    bits.append(json.dumps(p.get("behaviour") or []))  # what each action did (recorded by the explorer)
    return " ".join(str(b) for b in bits).lower()


def _case_text(c: dict) -> str:
    """What a test case is about: its title, steps and expected result (a large case lists every check it makes
    there) - but not a 'click each button' step: a click proves nothing."""
    steps = [str(s) for s in (c.get("steps") or []) if not CLICK_ONLY.search(str(s))]
    expected = "; ".join(e for e in str(c.get("expected") or "").split("; ") if not CLICK_ONLY.search(e))
    return f"{c.get('title', '')} {' '.join(steps)} {expected}".lower()


def _case_paths(c: dict, by_slug: dict) -> set:
    out = {_path(c.get("url") or "")} if c.get("url") else set()
    return out | {by_slug[s] for s in c.get("pages") or [] if s in by_slug}


def _verifies(c: dict) -> bool:
    """Does this case check a RESULT (not only 'it can be clicked' / 'the page opens')?"""
    return c.get("oracle") not in ("smoke", "click") and not CLICK_ONLY.search(c.get("title", ""))


def measure(run_dir, truth: dict | None = None, bugs: bool = False, visited: list | None = None) -> dict:
    run_dir = Path(run_dir)
    app_map = _read(run_dir / "app_map.json", [])
    cases = _read(run_dir / "test_cases.json", [])
    results = _read(run_dir / "results.json", [])
    crawl = _read(run_dir / "crawl.json", {})
    cov = _read(run_dir / "coverage.json", {})
    registry = _read(run_dir / "registry.json", None)
    status = Counter(c.get("execution_status") for c in cases)
    outcome = Counter(r.get("outcome") for r in results)
    from .report_clarity import case_status_counts, coverage_limitations, pages_coverage
    tc = {"planned": len(cases), **{k.lower().replace(" ", "_"): status.get(k, 0)
                                    for k in ("Passed", "Failed", "Flaky", "Skipped", "Blocked",
                                              "Inconclusive", "Not run")}}
    out = {
        "run": run_dir.name,
        "pages": {"discovered": len(app_map), "logged_in": sum(1 for p in app_map if p.get("auth")),
                  "failed": sum(1 for p in app_map if p.get("error") or (p.get("status") or 0) >= 400),
                  "not_visited": crawl.get("not_visited_count", 0), "sampled": crawl.get("sampled", 0)},
        "pages_coverage": pages_coverage(crawl, app_map),
        "test_cases": {**tc,
                       "click_only": sum(1 for c in cases if CLICK_ONLY.search(c.get("title", ""))
                                         or any(CLICK_ONLY.search(str(s)) for s in c.get("steps") or [])),
                       "exploratory": sum(1 for c in cases if c.get("oracle") == "observed")},
        "result_status_counts": case_status_counts(dict(tc, pending=status.get("Pending", 0))),
        "pytest_tests": {"total": len(results), **{k: outcome.get(k, 0) for k in
                                                  ("passed", "failed", "error", "skipped", "inconclusive")}},
        "coverage_claimed": {"tested": cov.get("tested"), "total": cov.get("total")},
        "coverage_limitations": coverage_limitations(
            crawl=crawl, limits=[], incomplete=False, discovery_only=False,
            feature_counts=(registry or {}).get("counts")),
        "actions": crawl.get("actions") or None,  # (recorded by the explorer: attempted / blocked / skipped ...)
        "overall_accuracy_percent": None,  # only a known-truth manifest can measure correctness; never invent it
    }
    if registry:
        out["registry"] = registry.get("counts")
    if not truth:
        out["note"] = ("Run-local counts only. No known-truth manifest was supplied, so overall accuracy "
                       "is not measured.")
        return out

    by_slug = {p.get("slug"): _path(p) for p in app_map}
    seen = [_path(p) for p in app_map if not p.get("error")]
    pages = {"known": len(truth["pages"]), "found": [], "missing": []}
    for k in truth["pages"]:
        hit = any(_matches(k["path"], s) for s in seen)
        pages["found" if hit else "missing"].append(k["path"] + ("" if hit or not k.get("how") else f"  ({k['how']})"))
    perm = [_path(x["url"]) for x in crawl.get("needs_permission", [])]
    pages["inaccessible_classified"] = {i["path"]: any(_matches(i["path"], x) for x in perm)
                                        for i in truth.get("inaccessible", [])}

    rows = []
    for f in truth["features"]:
        here = [p for p in app_map if _matches(f["page"], _path(p))]
        here_paths = {_path(p) for p in here}
        detected = any(re.search(f["detect"], _evidence(p), re.I) for p in here)
        mine = [c for c in cases if re.search(f["test"], _case_text(c), re.I)
                and (f.get("anywhere") or _case_paths(c, by_slug) & here_paths)]
        ran = [c for c in mine if c.get("execution_status") in RAN]
        verified = [c for c in ran if c.get("execution_status") == "Passed" and _verifies(c)]
        failed = [c for c in ran if c.get("execution_status") == "Failed"]
        expect = f.get("expect", "verified")
        if expect == "unsupported":  # (a closed shadow root: reported as unsupported - never claimed as tested)
            correct = any(re.search(f["detect"], json.dumps(p.get("unsupported") or []), re.I) for p in here) \
                and not verified
        elif expect == "blocked":
            correct = any(c.get("execution_status") == "Blocked" for c in mine)
        elif expect == "needs_login":
            correct = not verified and any(c.get("execution_status") == "Skipped" and LOGIN_NEEDED.search(
                f"{c.get('actual_result')} {c.get('skip_reason')}") for c in mine)
        elif bugs and f.get("bug"):
            correct = bool(failed)  # the planted bug was caught
        elif bugs:  # (with bugs planted, a large case also fails because of a bug elsewhere: judged on the clean run)
            correct = None
        else:
            correct = bool(verified) and not failed
        rows.append({"id": f["id"], "expect": "catch bug" if bugs and f.get("bug") else expect, "detected": detected,
                     "tested": bool(ran), "verified": bool(verified), "correct": correct,
                     "statuses": sorted({str(c.get("execution_status")) for c in mine}),
                     "cases": [c.get("tc_id") for c in mine]})
    n = len(rows)
    judged = [r for r in rows if r["correct"] is not None]
    out["truth"] = {
        "pages": pages,
        "features": {"known": n, "detected": sum(r["detected"] for r in rows), "tested": sum(r["tested"] for r in rows),
                     "verified": sum(r["verified"] for r in rows), "judged": len(judged),
                     "correct": sum(bool(r["correct"]) for r in judged), "rows": rows},
    }
    planted: dict[str, list] = {}
    for f in truth["features"]:
        if f.get("bug"):
            planted.setdefault(f["bug"], []).append(f["id"])
    # a failure is explained by a planted bug when it says what that bug does (its signature)
    signs = [re.compile(b["signature"], re.I) for b in truth.get("bugs", {}).values() if isinstance(b, dict)]
    explained = lambda c: bugs and any(s.search(c.get("actual_result") or "") for s in signs)  # noqa: E731
    if bugs:
        row = {r["id"]: r for r in rows}
        caught = sorted(b for b, fids in planted.items() if any(row[f]["correct"] for f in fids))
        out["truth"]["bugs"] = {
            "planted": len(planted), "caught": caught,
            "false_pass": sorted(b for b, fids in planted.items()
                                 if b not in caught and any(row[f]["verified"] for f in fids)),
            "not_tested": sorted(b for b, fids in planted.items()
                                 if b not in caught and not any(row[f]["verified"] for f in fids)),
        }
    # a failed case whose finding is a QUESTION (a rule between fields not kept, a control that did nothing) is asked,
    # not claimed as a bug: listed apart, never a false alarm
    failures = _read(run_dir / "failures.json", [])
    asked = {f.get("tc_id") for f in failures if f.get("category") in ("rule_violation", "suspect")}
    alarms = [c for c in cases if c.get("execution_status") == "Failed" and not explained(c)
              and c.get("tc_id") not in asked]
    out["truth"]["false_alarms"] = [{"tc_id": c.get("tc_id"), "title": c.get("title"),
                                     "why": (c.get("actual_result") or "")[:200]} for c in alarms]
    out["truth"]["questions"] = [{"tc_id": c.get("tc_id"), "title": c.get("title"),
                                  "why": (c.get("actual_result") or "")[:200]}
                                 for c in cases if c.get("tc_id") in asked and c.get("execution_status") == "Failed"]
    if truth.get("frames"):  # embedded frames: found (testable) and their controls tested
        frames = [dict(fr, page=_path(p)) for p in app_map for fr in p.get("frames") or []]
        text = " ".join(_case_text(c) for c in cases if c.get("execution_status") in RAN)
        rows_f = []
        for k in truth["frames"]:
            fr = next((x for x in frames if _matches(k["page"], x["page"]) and str(x.get("name", "")).lower()
                       == k["name"].lower() and x.get("status") == "testable"), None)
            controls = [x for p in app_map for x in p.get("buttons", []) + p.get("inputs", [])
                        if fr and x.get("frame_path") == fr["path"]]
            names = [(x.get("text") or x.get("label") or "").strip().lower() for x in controls]
            rows_f.append({"frame": k["name"], "found": bool(fr), "depth_ok": bool(fr) and len(fr["path"]) == k["depth"],
                           "tested": any(n and n in text for n in names)})
        out["truth"]["frames"] = {"known": len(rows_f), "found": sum(r["found"] for r in rows_f),
                                  "tested": sum(r["tested"] for r in rows_f), "rows": rows_f}
    if visited is not None:
        out["truth"]["never_requested_but_done"] = [r for r in truth.get("never", []) if r in visited]
    return out


def summary_line(m: dict) -> str:
    t = m.get("truth")
    if not t:
        return f"{m['pages']['discovered']} pages, {m['test_cases']['planned']} test cases"
    f, p = t["features"], t["pages"]
    s = (f"pages {len(p['found'])}/{p['known']} · features detected {f['detected']}/{f['known']} · tested "
         f"{f['tested']}/{f['known']} · verified {f['verified']}/{f['known']} · correct {f['correct']}/{f['judged']} · "
         f"false alarms {len(t['false_alarms'])}")
    if "bugs" in t:
        b = t["bugs"]
        s += f" · bugs caught {len(b['caught'])}/{b['planted']} (false passes: {len(b['false_pass'])})"
    if t.get("frames"):
        s += f" · frames found {t['frames']['found']}/{t['frames']['known']}, tested {t['frames']['tested']}"
    if t.get("questions"):
        s += f" · questions {len(t['questions'])}"
    return s


def main() -> None:
    ap = argparse.ArgumentParser(description="Accuracy of a finished test run")
    ap.add_argument("run_dir")
    ap.add_argument("--truth", help="known-truth manifest (JSON) of a practice website")
    ap.add_argument("--bugs", action="store_true", help="the website had its planted bugs switched on")
    ap.add_argument("--out", help="write the numbers to this JSON file (else they are printed)")
    a = ap.parse_args()
    truth = json.loads(Path(a.truth).read_text(encoding="utf-8")) if a.truth else None
    m = measure(a.run_dir, truth, a.bugs)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(m, indent=2), encoding="utf-8")
    else:
        print(json.dumps(m, indent=2))
    print(summary_line(m))


if __name__ == "__main__":
    main()
