"""One canonical set of numbers for a finished run. Every total of the report, the summary, the chat and Excel is
derived from the SAME records - results.json (every single test that ran), test_cases.json (every designed test case
with its result), registry.json (every page and feature found) and failures.json (every finding) - and the numbers
are CHECKED against each other: a total that does not add up is shown as a failed consistency check, never hidden.

Kinds of numbers, never mixed into one percentage:
  single tests   every pytest test that ran, in 4 groups: URL and link checks · page checks (opens, no JavaScript
                 errors, pictures) · input value checks · functional tests (features, journeys, learned behaviour)
  assertions     the checks (assert / expect) the single tests executed
  test cases     the designed test cases (one case can run several single tests) and their results
  workflows      the end-to-end journeys
  pages,         from the registry: discovered -> inspected -> test generated -> tested -> verified, and every page /
  features       feature that is not verified, with the reason
  findings       application defects vs. problems of the test scripts vs. expectations to review
The headline pass rate is the share of FUNCTIONAL test cases that passed, of the functional test cases that gave a
verdict (passed, failed or flaky). Link checks, page checks and input checks have their own rates and never inflate it.
"""
import json
from collections import Counter
from pathlib import Path

GROUPS = {"links": "URL and link checks",
          "page_checks": "Page checks (each page opens, no JavaScript errors, pictures load)",
          "input_checks": "Input value checks (values typed into boxes - forms are never sent)",
          "functional": "Functional tests (features, journeys, learned behaviour)"}
SMALL_CASES = {"site_links": "links", "site_pages_open": "page_checks", "site_no_js_errors": "page_checks",
               "site_images": "page_checks", "site_input_values": "input_checks"}
CASE_STATUSES = ("Passed", "Failed", "Flaky", "Inconclusive", "Skipped", "Blocked", "Not run", "Pending")
EXECUTED = ("Passed", "Failed", "Flaky", "Inconclusive")  # its checks ran (skipped / blocked / not run: they did not)
FINDING_KIND = {  # failures.json category -> what kind of finding it is
    "product_defect": "application_defects", "assertion_failure": "to_review", "test_defect": "test_problems",
    "locator": "test_problems", "timeout": "test_problems", "infrastructure": "test_problems",
    "auth_problem": "auth_or_data", "test_data": "auth_or_data", "inconclusive": "inconclusive", "flaky": "flaky",
    "rule_violation": "to_review", "suspect": "to_review", "third_party": "third_party", "test_mistake": "test_problems",
    "untriaged": "to_review"}


def result_group(r: dict) -> str:
    if r.get("verification_level") == "input_only":
        return "input_checks"
    f = r.get("file") or ""
    if f == "test_all_links.py":
        return "links"
    if f == "test_site.py":
        return "page_checks"
    if f.endswith("_data.py"):
        return "input_checks"
    return "functional"


def case_group(c: dict) -> str:
    if c.get("journey") == "form" or c.get("verification_level") == "input_only":
        return "input_checks"
    return SMALL_CASES.get(c.get("id"), "functional")


def _outcomes(rs: list[dict]) -> dict:
    o = Counter(r.get("outcome") for r in rs)
    return {"total": len(rs), "passed": o["passed"], "failed": o["failed"] + o["error"], "skipped": o["skipped"],
            "inconclusive": o["inconclusive"], "flaky": sum(1 for r in rs if r.get("flaky")),
            "assertions": sum(int(r.get("checks") or 0) for r in rs)}


def _statuses(cases: list[dict]) -> dict:
    s = Counter(c.get("execution_status") or "Not run" for c in cases)
    out = {k.lower().replace(" ", "_"): s.get(k, 0) for k in CASE_STATUSES}
    out.update(planned=len(cases), executed=sum(s.get(k, 0) for k in EXECUTED),
               not_executed=sum(s.get(k, 0) for k in CASE_STATUSES if k not in EXECUTED))
    return out


def _rate(name: str, num: int, den: int, what: str) -> dict:
    return {"name": name, "passed": num, "of": den, "percent": round(100 * num / den) if den else None,
            "denominator": what}


def build(results: list[dict], cases: list[dict], registry: dict | None = None, failures: list[dict] | None = None,
          crawl: dict | None = None, test_dir: Path | None = None) -> dict:
    """The canonical numbers of one run + the consistency checks (see the top of this file)."""
    from .excel import automation_status, case_hits, case_result
    failures, crawl = failures or [], crawl or {}
    groups = {g: dict(_outcomes([r for r in results if result_group(r) == g]), label=label)
              for g, label in GROUPS.items()}
    tc = _statuses(cases)
    tc["automated"] = sum(automation_status(c, test_dir)[0] == "Automated" for c in cases) if test_dir else None
    by_group = {g: _statuses([c for c in cases if case_group(c) == g]) for g in GROUPS}
    by_group["blocked"] = _statuses([c for c in cases if c.get("blocked")])
    functional = [c for c in cases if case_group(c) == "functional" and not c.get("blocked")]
    fs = _statuses(functional)

    workflows = [c for c in cases if case_group(c) != "input_checks"
                 and (c.get("kind") == "journey" or (c.get("ai") and c.get("kind") == "flow"))]
    wf_rows = []
    for c in workflows:
        hits = case_hits(c, results)
        steps = [s for r in hits for s in r.get("steps") or []]
        wf_rows.append({"tc_id": c.get("tc_id"), "title": c.get("title"), "status": c.get("execution_status"),
                        "steps_verified": steps, "detail": (c.get("actual_result") or "")[:300]})
    wf = _statuses(workflows)

    kinds = Counter(FINDING_KIND.get(f.get("category"), "other") for f in failures if f.get("source") == "test")
    crawler = Counter(f.get("test") for f in failures if f.get("source") == "crawler")
    findings = {"from_tests": sum(kinds.values()), "application_defects": kinds["application_defects"],
                "test_problems": kinds["test_problems"], "to_review": kinds["to_review"],
                "auth_or_data": kinds["auth_or_data"], "inconclusive": kinds["inconclusive"], "flaky": kinds["flaky"],
                "by_category": dict(Counter(f.get("category") for f in failures if f.get("source") == "test")),
                "seen_while_crawling": sum(crawler.values()), "crawling_by_type": dict(crawler),
                "bug_reports": sum(1 for f in failures if f.get("bug"))}

    reg = registry or {}
    rc = reg.get("counts") or {}
    untested_pages = [{"page": pg.get("pattern"), "state": pg.get("state"), "why": pg.get("why") or ""}
                      for pg in (reg.get("pages") or {}).values() if pg.get("state") != "verified"]
    # pages a visitor could not open (sent to the login page): never reached without a test account
    untested_pages += [{"page": x.get("url"), "state": "not reached",
                        "why": "a visitor is sent to the login page - needs a test account"}
                       for x in crawl.get("needs_login") or []]
    untested_features = [{"id": f["id"], "name": f.get("name"), "level": f.get("level"), "status": f.get("status"),
                          "why": f.get("why") or ""}
                         for f in (reg.get("features") or {}).values() if f.get("status") != "verified"]

    links, page_checks = groups["links"], groups["page_checks"]
    rates = [
        _rate("Functional test cases passed", fs["passed"], fs["passed"] + fs["failed"] + fs["flaky"],
              "functional test cases that gave a verdict (passed, failed or flaky); link, page and input checks are "
              f"not in it; {fs['blocked']} blocked, {fs['skipped']} skipped, {fs['inconclusive']} inconclusive and "
              f"{fs['not_run'] + fs['pending']} not-run test cases are listed separately"),
        _rate("URL and link checks passed", links["passed"], links["passed"] + links["failed"],
              f"link checks that gave a verdict ({links['skipped']} skipped: other websites that refuse checks, "
              "pages that need other permissions)"),
        _rate("Page checks passed", page_checks["passed"], page_checks["passed"] + page_checks["failed"],
              "page checks (opens, no JavaScript errors, pictures) that gave a verdict"),
        _rate("Input value checks passed", groups["input_checks"]["passed"],
              groups["input_checks"]["passed"] + groups["input_checks"]["failed"],
              f"input value checks that gave a verdict ({groups['input_checks']['inconclusive']} inconclusive: the "
              "box itself does not check the value, the form was not sent)"),
    ]
    if rc:
        F, P = rc.get("features") or {}, rc.get("pages") or {}
        rates.append(_rate("Features verified", F.get("verified", 0), F.get("discovered", 0),
                           "every feature / control found on the pages that were reached (registry)"))
        rates.append(_rate("Page patterns verified", P.get("verified", 0), P.get("discovered", 0),
                           "every page pattern found (a pattern with many pages, e.g. one product page per product, "
                           "counts once)"))
    from .report_clarity import case_status_counts, feature_status_counts
    out = {
        "single_tests": dict(_outcomes(results), groups=groups),
        "assertions": {"executed": sum(int(r.get("checks") or 0) for r in results),
                       **{g: groups[g]["assertions"] for g in GROUPS}},
        "test_cases": dict(tc, by_group=by_group, functional=fs),
        "workflows": dict(wf, list=wf_rows),
        "findings": findings,
        "pages": dict(rc.get("pages") or {}, needs_login=len(crawl.get("needs_login") or []),
                      untested=untested_pages[:300]),
        "features": dict(rc.get("features") or {}, untested=untested_features[:400]),
        "rates": rates,
        "headline": rates[0],
        # Additive clarity buckets for reports/UI - never mix into one "accuracy %"
        "result_status_counts": case_status_counts(tc),
        "feature_status_counts": feature_status_counts(rc.get("features") or {}),
    }
    out["consistency"] = consistency(out, results, cases, registry, failures, case_result, case_hits)
    out["consistency"] += more_checks(registry, test_dir)
    out["consistent"] = all(c["ok"] for c in out["consistency"])
    return out


def more_checks(registry: dict | None, test_dir: Path | None) -> list[dict]:
    """The checks of the stronger evidence (Steps 3-12): a verified feature never rests on a weak check only, every
    smoke / suspect / rule-question feature has the test that made it so, the frames and the created test data add up."""
    out = []
    feats = list(((registry or {}).get("features") or {}).values())
    weak_only = [f["id"] for f in feats if f.get("status") == "verified" and f.get("decided_by") and not any(
        x.get("strong", True) and x["status"] in ("Passed", "Flaky") for x in f["decided_by"])]
    out.append(_check("No verified feature rests on a weak check only (no errors / a status)", not weak_only,
                      f"{len(weak_only)} feature(s): {weak_only[:6]}" if weak_only else
                      "every verified feature has a passed test that checked a state or a value"))
    odd = [f["id"] for f in feats if f.get("status") in ("smoke", "suspect", "rule_violation") and not f.get("decided_by")]
    out.append(_check("Every smoke / suspect / rule-question feature has the test that made it so", not odd,
                      f"{len(odd)} without a deciding test: {odd[:6]}" if odd else "each one has its test"))
    run_dir = Path(test_dir).parent if test_dir else None
    if run_dir and (run_dir / "app_map.json").exists():
        try:
            pages = json.loads((run_dir / "app_map.json").read_text(encoding="utf-8"))
        except ValueError:
            pages = []
        frames = [fr for p in pages for fr in p.get("frames") or []]
        st = Counter(fr.get("status") for fr in frames)
        out.append(_check("Frames: testable + external + unreachable = frames found",
                          st["testable"] + st["external"] + st["unreachable"] == len(frames),
                          f"{st['testable']} + {st['external']} + {st['unreachable']} = {len(frames)}"))
    if run_dir and (run_dir / "created.json").exists():
        try:
            c = json.loads((run_dir / "created.json").read_text(encoding="utf-8"))
        except ValueError:
            c = {}
        if c:
            out.append(_check("Test data: created = deleted + left for manual cleanup",
                              c["created"] == c["deleted"] + len(c["left"]),
                              f"{c['created']} = {c['deleted']} + {len(c['left'])}"))
    return out


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"check": name, "ok": bool(ok), "detail": detail}


def consistency(m: dict, results, cases, registry, failures, case_result, case_hits) -> list[dict]:
    """Do the totals add up? Each check says what it compared."""
    st, tc, out = m["single_tests"], m["test_cases"], []
    parts = st["passed"] + st["failed"] + st["skipped"] + st["inconclusive"]
    out.append(_check("Every single test has exactly one outcome", parts == st["total"],
                      f"{st['passed']} passed + {st['failed']} failed + {st['skipped']} skipped + {st['inconclusive']} "
                      f"inconclusive = {parts}; single tests run: {st['total']}"))
    g = st["groups"]
    in_groups = sum(x["total"] for x in g.values())
    out.append(_check("The 4 groups of single tests add up to all single tests", in_groups == st["total"],
                      " + ".join(f"{x['total']} {k}" for k, x in g.items()) + f" = {in_groups}; all: {st['total']}"))
    n = sum(tc[k.lower().replace(" ", "_")] for k in CASE_STATUSES)
    out.append(_check("Every test case has exactly one status", n == tc["planned"],
                      f"sum of the statuses = {n}; test cases planned: {tc['planned']}"))
    out.append(_check("Executed + not executed = planned test cases",
                      tc["executed"] + tc["not_executed"] == tc["planned"],
                      f"{tc['executed']} executed (passed, failed, flaky, inconclusive) + {tc['not_executed']} not "
                      f"executed (skipped, blocked, not run) = {tc['executed'] + tc['not_executed']}; planned: "
                      f"{tc['planned']}"))
    wrong = [c.get("tc_id") for c in cases if c.get("execution_status") not in (None, "Pending")
             and case_result(c, results)[0] != c.get("execution_status")]
    out.append(_check("Each test case's status is the result of its own single tests", not wrong,
                      f"{len(wrong)} test case(s) whose status does not follow from their tests: {wrong[:8]}" if wrong
                      else "every status recomputed from results.json matches"))
    owned = set()
    for c in cases:
        owned.update(r["nodeid"] for r in case_hits(c, results))
    orphans = [r["nodeid"] for r in results if r["nodeid"] not in owned and r.get("test") != "(collection)"]
    out.append(_check("Every single test belongs to a test case", not orphans,
                      f"{len(orphans)} single test(s) belong to no test case: {orphans[:5]}" if orphans
                      else f"all {len(results)} single tests are counted in a test case"))
    if registry and registry.get("counts"):
        F = registry["counts"]["features"]
        statuses = Counter(f["status"] for f in registry["features"].values())
        out.append(_check("Every registered feature has exactly one status", sum(statuses.values()) == F["discovered"],
                          f"{dict(statuses)} = {sum(statuses.values())}; discovered: {F['discovered']}"))
        by_tc = {c.get("tc_id"): c for c in cases}
        bad_v, bad_f = [], []
        for f in registry["features"].values():
            if "decided_by" in f:  # (what decided it, for THIS feature: a site-wide case by the feature's own tests)
                d = f["decided_by"]
                if f["status"] == "verified" and not any(  # (a flaky test passed on its retry: its retry checked it)
                        x["status"] in ("Passed", "Flaky") and ((x.get("checks") or 0) > 0 or x["status"] == "Flaky")
                        and (x["how"] == "verifies" or x["how"] == "uses") for x in d):
                    bad_v.append(f["id"])
                elif f["status"] == "failed" and not any(x["status"] == "Failed" and x["how"] == "verifies" for x in d):
                    bad_f.append(f["id"])
                continue
            checks = [by_tc.get(t["tc_id"]) for t in f.get("tests") or [] if t.get("how") == "verifies"]
            checks = [c for c in checks if c]
            used = [by_tc.get(t["tc_id"]) for t in f.get("tests") or [] if t.get("how") == "uses"]  # (journeys)
            if f["status"] == "verified":
                proof = [c for c in checks + [u for u in used if u] if c.get("execution_status") in ("Passed", "Flaky")
                         and any(int(r.get("checks") or 0) > 0 for r in case_hits(c, results))]
                if not proof:
                    bad_v.append(f["id"])
            elif f["status"] == "failed" and not any(c.get("execution_status") == "Failed" for c in checks):
                bad_f.append(f["id"])
        out.append(_check("Every verified feature has a passed test case that checked its result", not bad_v,
                          f"{len(bad_v)} verified feature(s) without a passed checking test: {bad_v[:6]}" if bad_v
                          else f"{F['verified']} verified feature(s), each with a passed test case that ran assertions"))
        out.append(_check("Every failed feature has a failed test case that checks it", not bad_f,
                          f"{len(bad_f)} failed feature(s) without a failed test of their own: {bad_f[:6]}" if bad_f
                          else f"{F['failed']} failed feature(s), each with its own failed test case"))
        P = registry["counts"]["pages"]
        out.append(_check("Pages: verified <= tested <= inspected <= discovered",
                          P["verified"] <= P["tested"] <= P["inspected"] <= P["discovered"],
                          f"{P['verified']} <= {P['tested']} <= {P['inspected']} <= {P['discovered']}"))
    answered = {r["nodeid"] for r in results if r.get("outcome") in ("failed", "error", "inconclusive")}
    from .finalization import finding_nodes
    found = set().union(*(finding_nodes(f) for f in failures if f.get("source") == "test")) if failures else set()
    out.append(_check("Every failed or inconclusive single test has its finding", answered == found,
                      f"{len(answered)} failed / inconclusive single test(s), {len(found)} covered by test finding(s)"
                      + (f"; without a finding: {sorted(answered - found)[:4]}" if answered - found else "")
                      + (f"; finding without a test: {sorted(found - answered)[:4]}" if found - answered else "")))
    wf = m["workflows"]
    n = sum(wf[k.lower().replace(" ", "_")] for k in CASE_STATUSES)
    out.append(_check("Workflow results add up", n == len(wf["list"]),
                      f"sum of the statuses = {n}; workflows: {len(wf['list'])}"))
    return out


def summary_lines(m: dict) -> list[str]:
    """The numbers in plain words (report, chat, final answer)."""
    st, tc, g = m["single_tests"], m["test_cases"], m["single_tests"]["groups"]
    h, f = m["headline"], m["findings"]
    lines = [
        f"Functional test cases: {h['passed']} of {h['of']} passed ({h['percent'] if h['percent'] is not None else '-'}%)"
        f" - {h['denominator']}.",
        f"Test cases: {tc['planned']} planned, {tc['executed']} executed - {tc['passed']} PASS, {tc['failed']} FAIL, "
        f"{tc['flaky']} flaky (counted under FAIL in clarity totals), {tc['inconclusive']} INCONCLUSIVE, "
        f"{tc['skipped']} SKIPPED, {tc['blocked']} BLOCKED, {tc['not_run'] + tc['pending']} NOT TESTED.",
        f"Single tests: {st['total']} ran ({st['passed']} passed, {st['failed']} failed, {st['skipped']} skipped, "
        f"{st['inconclusive']} inconclusive) - " + ", ".join(f"{x['total']} {k.replace('_', ' ')}" for k, x in g.items())
        + f"; {m['assertions']['executed']} assertions executed.",
        f"Findings: {f['application_defects']} application defect(s), {f['test_problems']} test-script / locator / "
        f"environment problem(s), {f['to_review']} expectation(s) to review, {f['auth_or_data']} login / test-data "
        f"problem(s), {f['inconclusive']} inconclusive; {f['seen_while_crawling']} issue(s) seen while crawling.",
    ]
    if m["workflows"]["list"]:
        w = m["workflows"]
        lines.append(f"Workflows (end-to-end): {w['passed']} passed, {w['failed'] + w['flaky']} failed, "
                     f"{w['blocked']} blocked, {w['skipped'] + w['inconclusive'] + w['not_run']} not proven, "
                     f"of {len(w['list'])}.")
    if m["features"].get("discovered") is not None:
        F, P = m["features"], m["pages"]
        lines.append(f"Features: {F.get('discovered', 0)} discovered, {F.get('tested', 0)} tested, "
                     f"{F.get('verified', 0)} verified, {F.get('failed', 0)} failed, {F.get('blocked', 0)} blocked; "
                     f"page patterns: {P.get('discovered', 0)} discovered, {P.get('verified', 0)} verified.")
    bad = [c for c in m["consistency"] if not c["ok"]]
    lines.append("All totals add up (consistency checks passed)." if not bad else
                 f"{len(bad)} consistency check(s) FAILED: " + "; ".join(c["check"] for c in bad))
    return lines
