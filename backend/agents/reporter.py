"""Agent 6 — Quality & Release Assessment + Report.

Release verdict is decided by FIXED RULES (not by the LLM's opinion):
  Insufficient Evidence -> nothing could be tested (start page failed / no tests ran)
  Not Ready             -> any page failed to load, or any high-severity product defect
  Ready with Risks      -> no blockers, but other defects / console errors / flaky tests
  Ready                 -> everything passed
Then writes runs/<run_id>/report.html: a simple, plain-English report (verdict in one sentence,
what works, what to fix and why, page by page), with the technical details folded at the bottom.
"""
import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from ..advice import build_fixes
from ..cost import fmt_usd, write_report as write_cost_report
from ..excel import write_workbook
from ..page_status import page_testable
from ..state import QAState
from ..story import headline, working_well
from .script_generator import _ident

COLORS = {"Ready": "#16a34a", "Ready with Risks": "#d97706", "Not Ready": "#dc2626",
          "Insufficient Evidence": "#64748b"}
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
PRIORITY_WORDS = {"critical": "Must fix", "high": "Fix first", "medium": "Should fix", "low": "Nice to fix"}


SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
# gave no answer about the website (a test mistake the AI saw on screen too: the test, not the website, was wrong)
NOT_ANSWERED = ("test_defect", "locator", "infrastructure", "timeout", "inconclusive", "test_data", "test_mistake")
# (an "assertion_failure" - an exploratory expectation not met - is a finding to review, never a release blocker)


def _gate(gid: str, name: str, status: str, detail: str, mandatory: bool = True) -> dict:
    """status: pass | fail (a blocker was found) | missing (not enough evidence) | risk (documented risk)."""
    return {"id": gid, "name": name, "status": status, "detail": detail, "mandatory": mandatory}


def quality_gates(state: QAState) -> list[dict]:
    """The release gates, from fixed rules (thresholds in .env: GATE_*). The AI never takes part in this.
    A run that did not finish (it crashed, was stopped or hit RUN_TIME_LIMIT_MIN) fails the first gate."""
    if state.get("target_type") == "mobile":
        from ..android_reporting import mobile_quality_gates
        return mobile_quality_gates(state)
    gates = _quality_gates(state)
    if state.get("incomplete"):
        gates.insert(0, _gate("run_complete", "The run finished", "missing",
                              state.get("incomplete_reason") or "The run did not finish."))
    return gates


def _quality_gates(state: QAState) -> list[dict]:
    from ..config import settings
    from .discovery import _auth_link
    app_map, results, failures = state.get("app_map", []), state.get("results", []), state.get("failures", [])
    login, crawl = state.get("login") or {}, state.get("crawl") or {}
    ok_pages = [p for p in app_map if page_testable(p)]
    gates = []

    if state.get("setup_error"):
        return [_gate("app_started", "The app could be started", "missing", state["setup_error"][:300])]
    start_ok = bool(app_map) and page_testable(app_map[0])
    others = [p for p in ok_pages if p is not app_map[0]] if app_map else []
    if not start_ok and len(others) < settings.gate_min_public_pages:
        out = (crawl.get("redirected_out") or [{}])[0].get("reason")
        return [_gate("start_page", "The start page opens", "missing",
                      "The start page could not be loaded" + (f" ({out})." if out else "."))]
    if start_ok:
        gates.append(_gate("start_page", "The start page opens", "pass", app_map[0].get("url", "")))
    else:  # it did not open (twice), but the website did: a slow / broken start page is a finding, not "no evidence"
        why = (app_map[0].get("error") or f"HTTP {app_map[0].get('status')}").splitlines()[0][:120]
        gates.append(_gate("start_page", "The start page opens", "risk",
                           f"The start page did not open ({why}), but {len(others)} other page(s) of the website did "
                           "and were tested.", mandatory=False))

    # login: was the app behind it tested?
    if login.get("found") and not login.get("logged_in"):
        public = [p for p in ok_pages if not _auth_link(p.get("final_url") or p["url"])]
        walled = login.get("required") or len(public) < settings.gate_min_public_pages
        status = "missing" if walled and settings.gate_login_required else "risk"
        gates.append(_gate("login", "The pages behind the login were tested", status,
                           login.get("note") or "Not logged in.", mandatory=settings.gate_login_required))
    elif login.get("logged_in"):
        expired = bool(login.get("session_expired"))
        gates.append(_gate("login", "The pages behind the login were tested", "risk" if expired else "pass",
                           "The login expired during the crawl - some pages behind it were not tested." if expired
                           else f"Logged in ({'; '.join(login.get('evidence') or [])})."))

    # route coverage — never claim exhaustive reachability when exploration is partial
    exploration = crawl.get("exploration") or {}
    actions = crawl.get("actions") or {}
    pending_urls = int(crawl.get("not_visited_count") or 0)
    partial_exploration = bool(
        crawl.get("limit_reached") or crawl.get("time_limit_reached") or crawl.get("stopped")
        or pending_urls > 0 or actions.get("not_tried_limit")
        or exploration.get("status") == "partial"
        or exploration.get("within_selected_scope") is False
        or exploration.get("actions_limited"))
    if len(ok_pages) < 1:
        gates.append(_gate("routes", "Pages could be visited", "missing", "No page could be opened."))
    elif partial_exploration:
        bits = []
        if crawl.get("limit_reached"):
            bits.append(f"page limit ({crawl.get('limit')})")
        if crawl.get("time_limit_reached") or crawl.get("stopped"):
            bits.append("crawl time limit / stop")
        if pending_urls:
            bits.append(f"{pending_urls} pending URL(s) not visited")
        if actions.get("not_tried_limit"):
            bits.append(f"{actions.get('not_tried_limit')} control interaction(s) not tried (per-page limit)")
        detail = ("Exploration is partial — this is not exhaustive reachability. "
                  + ("; ".join(bits) + ". " if bits else "")
                  + f"{len(ok_pages)} page(s) visited. Visited URLs ≠ every route pattern, control, "
                    "interaction check, feature or business workflow.")
        gates.append(_gate("routes", "Route exploration within selected limits", "risk", detail, mandatory=False))
    else:
        gates.append(_gate(
            "routes", "Discovered routes visited within selected scope", "pass",
            f"{len(ok_pages)} discovered page(s) visited within the selected exploration scope. "
            "This is not a claim that every possible URL, control, feature or business workflow was reached.",
            mandatory=False))

    # execution evidence
    answered = [r for r in results if r["outcome"] in ("passed", "failed", "error", "inconclusive")]
    if not answered:
        gates.append(_gate("tests_ran", "Tests were executed", "missing", "No test gave a result."))
        return gates
    from ..metrics import GROUPS, result_group
    by_group = {g: sum(1 for r in results if result_group(r) == g) for g in GROUPS}
    gates.append(_gate("tests_ran", "Tests were executed", "pass",
                       f"{len(results)} single test(s) ran ({by_group['functional']} functional, {by_group['links']} "
                       f"link checks, {by_group['page_checks']} page checks, {by_group['input_checks']} input value "
                       f"checks): {len(answered)} gave a result, {len(results) - len(answered)} skipped."))
    from .failure_analysis import covered_result_nodeids
    covered = covered_result_nodeids(failures)
    bad_results = [r for r in results if r.get("outcome") in ("failed", "error", "inconclusive")]
    unlinked = [r for r in bad_results if r.get("nodeid") and r["nodeid"] not in covered]
    no_answer = [f for f in failures if f.get("source") == "test" and f.get("category") in NOT_ANSWERED]
    # Failed/inconclusive results with no finding cannot claim "0 unreliable" - treat as unanswered.
    unreliable = len(no_answer) + len(unlinked)
    share = unreliable / max(1, len(answered))
    if unlinked and not no_answer and not any(f.get("source") == "test" for f in failures):
        auto_status = "missing"  # empty findings while failures remain → Insufficient Evidence
    elif unreliable and share >= settings.gate_max_automation_errors:
        auto_status = "missing"
    elif unreliable:
        auto_status = "risk"
    else:
        auto_status = "pass"
    auto_detail = (f"{unreliable} of {len(answered)} test(s) could not tell whether the website works "
                   f"(script, network, time limit or no check) - limit {settings.gate_max_automation_errors:.0%}.")
    if unlinked:
        auto_detail += f" {len(unlinked)} failed/inconclusive result(s) have no linked finding yet."
    gates.append(_gate("automation", "Tests produced reliable answers", auto_status, auto_detail))
    timed_out = "THE RUN WAS STOPPED BY ITS TIME LIMIT" in " ".join(state.get("log", []))
    if timed_out:
        gates.append(_gate("time_limit", "All tests finished in time", "risk",
                           "The test run hit its time limit; the remaining tests did not run.", mandatory=False))

    # quality: blocking website bugs
    limit = SEV_RANK.get(settings.gate_block_severity, 1)
    blockers = [f for f in failures if f["category"] == "product_defect" and SEV_RANK.get(f["severity"], 9) <= limit
                and f.get("confidence") != "low"]
    confirmed_blockers = [f for f in blockers if not f.get("provisional")]
    provisional_open = [f for f in failures if f.get("provisional")]
    if confirmed_blockers:
        block_status, block_detail = "fail", (
            f"{len(confirmed_blockers)} blocking problem(s): "
            + "; ".join(sorted({f['explanation'][:80] for f in confirmed_blockers}))[:400])
    elif unlinked:
        # Empty/unlinked findings must never clear a "no bugs" gate while failures remain.
        block_status, block_detail = "missing", (
            f"Cannot confirm absence of blockers: {len(unlinked)} failed/inconclusive test(s) have no finding yet.")
    elif provisional_open or blockers:
        n = len(provisional_open) or len(blockers)
        block_status, block_detail = "missing", (
            f"Insufficient Evidence: {n} finding(s) are still provisional / untriaged — "
            "cannot confirm absence of blockers while triage is open.")
    else:
        block_status, block_detail = "pass", (
            "No high-severity product defects confirmed among triaged findings "
            "(not a claim that the product has zero bugs).")
    gates.append(_gate("blockers", f"No website bug of severity '{settings.gate_block_severity}' or higher",
                       block_status, block_detail))
    # critical user journeys (log in, shopping, orders ...) must all pass
    from ..excel import case_result
    journeys = [(c, case_result(c, results)[0]) for c in state.get("test_cases", [])
                if c.get("kind") == "journey" and c.get("priority") == "high"]
    if journeys:  # (a journey that failed because of OUR script is "not proven", not a website failure)
        cat = {f.get("tc_id"): f["category"] for f in failures if f.get("tc_id")}
        bad = [c["title"] for c, s in journeys if s in ("Failed", "Flaky") and cat.get(c.get("tc_id")) == "product_defect"]
        open_ = [c["title"] for c, s in journeys if s in ("Inconclusive", "Not run", "Skipped")
                 or (s in ("Failed", "Flaky") and c["title"] not in bad)]
        gates.append(_gate("journeys", "All critical user journeys pass",
                           "fail" if bad else "risk" if open_ else "pass",
                           (f"Failing: {'; '.join(bad)[:300]}" if bad else
                            f"Not proven: {'; '.join(open_)[:300]}" if open_ else
                            f"All {len(journeys)} critical journey(s) passed."), mandatory=bool(bad)))
    # feature coverage: registry features ≠ business workflows; never claim complete product coverage with gaps
    # or while exploration is still partial (pending URLs / interaction limits).
    fc = state.get("feature_counts")  # (the registry, after the results: set by reporter_agent)
    if fc:
        F, P = fc["features"], fc["pages"]
        gaps = F["unresolved"] + F["clicked_only"] + P.get("not_reached", 0)
        incomplete_cov = bool(gaps or partial_exploration)
        feat_detail = (
            ("Not complete - " if incomplete_cov else "")
            + f"{F['discovered']} feature(s) found: {F['verified']} verified, {F['failed']} failed, {F['blocked']} "
              f"blocked (protected), {F['needs_login']} need a test account, {F['inconclusive']} inconclusive, "
              f"{F['clicked_only']} only clicked, {F['skipped']} skipped, {F['unresolved']} not tested; "
              f"{P.get('not_reached', 0)} page(s) not reached (limits), {P.get('sampled_out', 0)} more page(s) of "
              "sampled address patterns. "
              "Counts are registry features / route patterns — not every control, interaction check or "
              "business workflow.")
        gates.append(_gate(
            "feature_coverage",
            "Features found were tested or explained" if incomplete_cov
            else "Every feature found was tested (or says why not)",
            "risk" if incomplete_cov else "pass", feat_detail, mandatory=False))
    # (another website's blocked tracker / ad is listed, never a risk of THIS website's release)
    others = [f for f in failures if f not in blockers and f["category"] not in NOT_ANSWERED + ("third_party",)]
    healed = [h for h in state.get("healing_log", []) if h["status"] in ("healed", "repaired")]
    risks = []
    if others:
        risks.append(f"{len(others)} other finding(s) to review (smaller bugs, console errors, flaky tests, login "
                     "problems).")
    if healed:
        risks.append(f"{len(healed)} test script(s) were repaired automatically - please review them.")
    if unlinked:
        risks.append(f"{len(unlinked)} failed/inconclusive result(s) still have no linked finding.")
    if provisional_open:
        risks.append(f"{len(provisional_open)} finding(s) remain provisional / untriaged.")
    findings_detail = (" ".join(risks) if risks else
                       "No further triaged findings beyond the gates above "
                       "(not a claim of zero bugs across the whole product).")
    gates.append(_gate("findings", "No other findings", "risk" if risks else "pass",
                       findings_detail, mandatory=False))
    return gates


def decide_verdict(state: QAState) -> tuple[str, list[str], list[dict]]:
    """Ready / Ready with Risks / Not Ready / Insufficient Evidence - calculated from the release gates."""
    gates = quality_gates(state)
    missing = [g for g in gates if g["status"] == "missing" and g["mandatory"]]
    failed = [g for g in gates if g["status"] == "fail"]
    risky = [g for g in gates if g["status"] == "risk" or (g["status"] == "missing" and not g["mandatory"])]
    if state.get("incomplete"):  # what was found is reported, but an unfinished run can never be "Ready" - reason first
        return "Insufficient Evidence", [g["detail"] for g in missing + failed] or [
            "The run did not finish — Insufficient Evidence until execution completes."], gates
    basic = [g for g in missing if g["id"] in ("app_started", "start_page", "tests_ran")]
    if basic:  # nothing (or nearly nothing) could be tested
        return "Insufficient Evidence", [g["detail"] for g in basic], gates
    if failed:
        return "Not Ready", [g["detail"] for g in failed] + [g["detail"] for g in missing], gates
    if missing:
        return "Insufficient Evidence", [g["detail"] for g in missing], gates
    if risky:
        return "Ready with Risks", [g["detail"] for g in risky], gates
    return "Ready", [
        "Every release gate passed for what this run executed. "
        "That is not a claim that every URL, feature or business workflow was tested, or that the product has zero bugs."
    ], gates


def consistency_reasons(metrics: dict | None) -> list[str]:
    """Surface metrics.consistent failures as prominent summary reasons when totals do not add up."""
    if not metrics or metrics.get("consistent", True):
        return []
    bad = [c for c in (metrics.get("consistency") or []) if not c.get("ok")]
    if not bad:
        return ["Metrics consistency FAILED: totals do not add up — see consistency checks."]
    detail = "; ".join(f"{c.get('check')}: {c.get('detail')}" for c in bad[:4])
    return [f"Metrics consistency FAILED ({len(bad)} check(s)): {detail}"]


def coverage_summary(state: QAState, run_dir: Path) -> dict:
    """Three DIFFERENT coverages, never mixed into one percentage."""
    from ..excel import automation_status, case_result
    crawl, app_map = state.get("crawl") or {}, state.get("app_map", [])
    visited = len(app_map)
    found = visited + crawl.get("not_visited_count", 0)
    cov = json.loads((run_dir / "coverage.json").read_text(encoding="utf-8")) if (run_dir / "coverage.json").exists() else {}
    cases, results = state.get("test_cases", []), state.get("results", [])
    test_dir = run_dir / "generated_tests"
    statuses = [case_result(c, results)[0] for c in cases]
    reasons: dict[str, int] = {}
    for s in crawl.get("skipped", []):
        key = s["reason"].split(" (")[0]
        reasons[key] = reasons.get(key, 0) + 1
    # pages: discovered -> inspected (opened + elements read) -> tested (a test ran on it) -> verified (one passed)
    by_page: dict[str, list[str]] = {}
    for c, s in zip(cases, statuses):
        for slug in c.get("pages") or [c.get("page")]:
            by_page.setdefault(slug, []).append(s)
    ran = ("Passed", "Failed", "Flaky", "Inconclusive")
    inspected = [p for p in app_map if not p.get("error")]
    feats = [c for c, s in zip(cases, statuses) if c.get("kind") == "feature"]
    feat_status = [s for c, s in zip(cases, statuses) if c.get("kind") == "feature"]
    journeys = [(c, s) for c, s in zip(cases, statuses) if c.get("kind") == "journey"]
    return {
        "pages": {"discovered": found, "inspected": len(inspected),
                  "tested": sum(1 for p in inspected if any(s in ran for s in by_page.get(p.get("slug"), []))),
                  "verified": sum(1 for p in inspected if "Passed" in by_page.get(p.get("slug"), [])),
                  "logged_in": sum(1 for p in inspected if p.get("auth")),
                  "needs_permission": len(crawl.get("needs_permission", [])),
                  "could_not_open": crawl.get("visited_failed", 0) - len(crawl.get("needs_permission", [])),
                  "not_reached": crawl.get("not_visited_count", 0), "sampled": crawl.get("sampled", 0),
                  "time_limit_reached": bool(crawl.get("time_limit_reached")),
                  "types": crawl.get("page_types", {})},
        "features": {"found": sum(len([f for f in p.get("features") or [] if f != "protected"]) for p in inspected),
                     "tests": len(feats), "run": sum(s in ran for s in feat_status),
                     "passed": feat_status.count("Passed")},
        "journeys": [{"title": c["title"], "status": s, "tc_id": c.get("tc_id")} for c, s in journeys],
        "blocked": [{"title": c["title"], "reason": c.get("skip_reason")} for c, s in zip(cases, statuses) if s == "Blocked"],
        "routes": {"found": found, "visited": visited, "failed": crawl.get("visited_failed", 0),
                   "logged_in": crawl.get("logged_in_pages", 0), "not_visited_limit": crawl.get("not_visited_count", 0),
                   "limit": crawl.get("limit"), "limit_reached": bool(crawl.get("limit_reached")),
                   "skipped": crawl.get("skipped_count", 0), "skipped_reasons": reasons,
                   "redirected_out": len(crawl.get("redirected_out", [])), "blocked_requests": crawl.get("blocked_count", 0),
                   "external_links": crawl.get("external_links", 0)},
        "components": {"found": cov.get("total", 0), "tested": cov.get("tested", 0)},
        "execution": {"cases": len(cases),
                      "automated": sum(automation_status(c, test_dir)[0] == "Automated" for c in cases),
                      # (executed = its checks ran: a blocked, skipped or not-run case was not executed)
                      "executed": sum(s in ("Passed", "Failed", "Flaky", "Inconclusive") for s in statuses),
                      **{s.lower().replace(" ", "_"): statuses.count(s)
                         for s in ("Passed", "Failed", "Flaky", "Skipped", "Blocked", "Inconclusive", "Not run")}},
    }


STATUS_WORDS = {"verified": "✓ verified", "failed": "✗ failed", "blocked": "⛔ blocked (protected)",
                "needs_login": "🔑 not tested - needs a test account", "inconclusive": "? inconclusive",
                "clicked_only": "tested - only clicked", "skipped": "– not tested - skipped",
                "test_generated": "test generated - did not run", "unresolved": "not tested"}


def _ratio(done: int, total: int) -> float:
    return 1.0 if total <= 0 else max(0.0, min(1.0, done / total))


def coverage_confidence(cov: dict, state: QAState, limits: list[dict]) -> dict:
    """Plain-English answer to: did this run cover the site thoroughly enough to trust the result?"""
    pages, routes, components, execution = cov["pages"], cov["routes"], cov["components"], cov["execution"]
    score, reasons, next_steps = 100, [], []

    if state.get("incomplete"):
        score -= 35
        reasons.append("the run stopped before every designed test finished")
        next_steps.append("resume or start a fresh run and let execution finish")
    if limits:
        score -= min(25, 8 * len(limits))
        next_steps.append("raise the page/time limits or split a large site into sections")

    route_rate = _ratio(routes["visited"], routes["found"])
    control_rate = _ratio(components["tested"], components["found"])
    execution_rate = _ratio(execution["executed"], execution["cases"])
    verified_page_rate = _ratio(pages["verified"], pages["discovered"])

    if route_rate < 1:
        score -= round((1 - route_rate) * 30)
        reasons.append(f"{routes['found'] - routes['visited']} discovered page(s) were not visited")
    if components["found"] and control_rate < 0.85:
        score -= round((0.85 - control_rate) * 45)
        reasons.append(f"{components['found'] - components['tested']} discovered control(s) were not used by tests")
        next_steps.append("review the Coverage sheet for controls marked not tested")
    if execution["cases"] and execution_rate < 0.9:
        score -= round((0.9 - execution_rate) * 45)
        reasons.append(f"{execution['cases'] - execution['executed']} designed test case(s) did not execute")
        next_steps.append("run again with TEST_WORKERS=1 and watch mode if tests are being interrupted")
    if execution["inconclusive"]:
        score -= min(20, execution["inconclusive"] * 2)
        reasons.append(f"{execution['inconclusive']} test(s) were inconclusive")
    if not execution["cases"]:
        score -= 35
        reasons.append("no test cases were designed")

    score = max(0, min(100, score))
    exploration = (state.get("crawl") or {}).get("exploration") or {}
    if exploration.get("status") == "partial" or exploration.get("within_selected_scope") is False:
        score = min(score, 59)
        reasons.append("exploration is partial — not exhaustive reachability")
    if score >= 85:
        label = "High"
        summary = ("Strong coverage evidence within the selected scope: discovered pages, controls and designed "
                   "tests that were in budget were exercised (not a whole-product exhaustive claim).")
    elif score >= 60:
        label = "Medium"
        summary = "Useful coverage evidence, but check the listed gaps before trusting it as complete."
    else:
        label = "Low"
        summary = "Coverage evidence is not enough yet; this run should be treated as partial."

    if not reasons:
        reasons.append("no major coverage gaps were detected within the selected exploration scope")
    if not next_steps:
        next_steps.append("use the report failures and screenshots as the next action list")
    return {
        "label": label, "score": score, "summary": summary, "reasons": reasons[:6], "next_steps": next_steps[:4],
        "rates": {
            "routes": round(route_rate * 100),
            "controls": round(control_rate * 100),
            "execution": round(execution_rate * 100),
            "verified_pages": round(verified_page_rate * 100),
        },
    }


def registry_html(run_dir: Path, state: QAState) -> str:
    """The feature registry in the report: separate counts per level, the coverage denominator, what exploring tried
    (and every limit it hit), and each feature that is NOT verified - with the reason."""
    from .. import registry
    from ..config import settings
    reg = registry.load(run_dir)
    if not reg or not reg.get("counts"):
        return ""
    c, a = reg["counts"], (state.get("crawl") or {}).get("actions") or {}
    P, F = c["pages"], c["features"]
    lvl = F["by_level"]
    open_ = [f for f in reg["features"].values() if f["status"] != "verified"]
    open_.sort(key=lambda f: (["failed", "unresolved", "test_generated", "clicked_only", "inconclusive", "needs_login",
                               "skipped", "blocked"].index(f["status"]) if f["status"] in STATUS_WORDS else 9, f["level"]))
    rows = "".join(f"<tr><td>{_e(STATUS_WORDS.get(f['status'], f['status']))}</td><td>{_e(f['level'])}</td>"
                   f"<td>{_e(f['name'])}</td><td class='url'>{_e(', '.join(f['pages'][:2]))}</td>"
                   f"<td>{_e(f.get('why') or '')}</td></tr>" for f in open_[:80])
    page_rows = "".join(f"<tr><td>{_e(pg['state'])}</td><td class='url'>{_e(pg['pattern'])}</td>"
                        f"<td>{_e(pg.get('why') or '')}</td></tr>"
                        for pg in reg["pages"].values() if pg["state"] != "verified")
    life = F.get("lifecycle") or {}
    budget = state.get("llm_budget_note") or ""
    return f"""<h2>Feature registry - every feature with its own result</h2>
<div class="nums">
  <div class="n"><b>{F['discovered']}</b><span>features / controls discovered</span></div>
  <div class="n"><b>{F['tested']}</b><span>tested</span></div>
  <div class="n ok"><b>{F['verified']}</b><span>verified (a test checked the RESULT and passed)</span></div>
  <div class="n"><b>{F['failed']}</b><span>failed</span></div>
</div>
<div class="box"><ul>
  <li>The way of a feature: {life.get('discovered', F['discovered'])} discovered → {life.get('inspected', '-')} inspected →
    {life.get('test_generated', '-')} with a test case → {life.get('tested', F['tested'])} tested →
    {life.get('verified', F['verified'])} verified</li>
  <li>By level: controls {lvl['control']['verified']} / {lvl['control']['discovered']} verified · features
    {lvl['feature']['verified']} / {lvl['feature']['discovered']} · workflows {lvl['workflow']['verified']} /
    {lvl['workflow']['discovered']}</li>
  <li>Blocked (protected, never performed): <b>{F['blocked']}</b> · need a test account: <b>{F['needs_login']}</b> ·
    inconclusive: <b>{F['inconclusive']}</b> · only clicked (no result checked): <b>{F['clicked_only']}</b> ·
    test generated but not run: <b>{F.get('test_generated', 0)}</b> ·
    not tested: <b>{F['unresolved']}</b> (each one says why below)</li>
  <li>Pages: {P['discovered']} page patterns discovered · {P['inspected']} inspected · {P['tested']} tested ·
    {P['verified']} verified · {P['needs_permission']} need other permissions · {P['failed_to_open']} could not open ·
    {P['not_reached']} not reached (limits) · {P['sampled_out']} more pages of a sampled pattern</li>
  <li>Exploring: {a.get('attempted', 0)} actions tried · {a.get('learned', 0)} with a visible effect ·
    {a.get('no_effect', 0)} without · {a.get('blocked', 0)} blocked · {a.get('skipped', 0)} skipped ·
    {a.get('not_tried_limit', 0)} not tried because of the limit (MAX_INTERACTIONS_PER_PAGE={a.get('limit_per_page', '-')}
    / CRAWL_TIME_LIMIT_MIN={settings.crawl_time_limit_min:g}) · AI budget LLM_BUDGET_USD={settings.llm_budget_usd:g} {_e(budget)}</li>
  <li class="muted">Counted: {_e(c.get('denominator', ''))}. 100% is never claimed beyond this.</li>
</ul>{_table(["Status", "Level", "Feature / control", "Page", "Why"], rows, "Every feature was verified.")}
<h4>Pages that are not verified - and why</h4>
{_table(["State", "Page (pattern)", "Why"], page_rows, "Every page was verified.")}</div>"""


def fill_case_results(cases: list[dict], results: list[dict], failures: list[dict], test_dir: Path) -> None:
    """Automation status, actual result, execution status and evidence of every test case (after the tests ran)."""
    from ..excel import automation_status, case_hits, case_result
    by_case = {f.get("tc_id"): f for f in failures if f.get("tc_id")}
    for c in cases:
        status, detail = case_result(c, results)
        hits = case_hits(c, results)
        c["automation_status"], c["automated_by"] = automation_status(c, test_dir)
        c["execution_status"] = status
        if detail:
            c["actual_result"] = detail
        elif status == "Passed":
            c["actual_result"] = "All checks passed"
        elif status == "Skipped" and hits:
            c["actual_result"] = "Skipped: " + (hits[0].get("error") or "")[:200]
        else:
            c["actual_result"] = status
        c["evidence"] = [x for r in hits for x in (r.get("screenshot"), r.get("trace")) if x][:10]
        if status == "Skipped" and not c.get("skip_reason"):
            c["skip_reason"] = c["actual_result"]
        f = by_case.get(c.get("tc_id"))
        if f:
            c["failure_category"], c["confidence"] = f.get("category_name"), f.get("confidence")


def compare_with_previous(state: QAState, run_dir: Path, cases: list[dict]) -> dict:
    """Regression view: this run's test cases against the last finished run of the same site (by stable ID)."""
    site = state.get("site_key", "")
    prev = None
    for d in sorted(run_dir.parent.glob(f"{site}_*"), key=lambda p: p.name, reverse=True):
        if not re.fullmatch(rf"{re.escape(site)}_\d{{8}}_\d{{6}}", d.name):
            continue  # (another site whose name starts the same)
        if d != run_dir and d.name < run_dir.name and (d / "summary.json").exists() and (d / "test_cases.json").exists():
            prev = d
            break
    if not prev:
        return {"previous_run": None}
    old = {c.get("tc_id") or c.get("id"): c for c in json.loads((prev / "test_cases.json").read_text(encoding="utf-8"))}
    now = {c.get("tc_id") or c.get("id"): c for c in cases}
    bad = ("Failed", "Flaky", "Inconclusive")
    rows = []
    for k, c in now.items():
        before = (old.get(k) or {}).get("execution_status")
        after = c.get("execution_status")
        change = ("new test case" if k not in old else "newly failing" if after in bad and before not in bad
                  else "fixed" if before in bad and after == "Passed" else "still failing" if after in bad
                  else "unchanged")
        rows.append({"tc_id": k, "title": c.get("title"), "before": before, "after": after, "change": change})
    rows += [{"tc_id": k, "title": c.get("title"), "before": c.get("execution_status"), "after": None,
              "change": "removed"} for k, c in old.items() if k not in now]
    summary_prev = json.loads((prev / "summary.json").read_text(encoding="utf-8"))
    counts = {}
    for r in rows:
        counts[r["change"]] = counts.get(r["change"], 0) + 1
    return {"previous_run": prev.name, "previous_verdict": summary_prev.get("verdict"),
            "previous_date": summary_prev.get("finished") or prev.name[-15:], "counts": counts, "cases": rows}


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _img(path: str | None, cls: str = "thumb") -> str:
    if not path:
        return ""
    return f'<a href="{_e(path)}" target="_blank"><img class="{cls}" src="{_e(path)}" loading="lazy" alt="screenshot"></a>'


def _code_html(c: dict | None) -> str:
    """'Code now -> Change to' block under a fix."""
    if not c or not c.get("before"):
        return ""
    out = f'<div class="codefix"><div class="clbl now">Code now</div><pre class="now">{_e(c["before"])}</pre>'
    if c.get("after"):
        who = "written by the AI - check it before you use it" if c.get("how") == "ai" else "built-in rule"
        out += (f'<div class="clbl to">Change to <span class="muted">· {who}</span>'
                f'<button class="copy" onclick="copyCode(this)">Copy</button></div><pre class="to">{_e(c["after"])}</pre>')
    return out + "</div>"


def _table(head: list[str], rows: str, empty: str) -> str:
    if not rows:
        return f'<p class="muted">{_e(empty)}</p>'
    return (f'<div class="tablewrap"><table><tr>{"".join(f"<th>{_e(h)}</th>" for h in head)}</tr>'
            f'{rows}</table></div>')


def _visual(run_dir: Path) -> dict | None:
    try:
        return json.loads((run_dir / "visual.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def visual_html(vis: dict | None) -> str:
    """The look of every page compared with its approved look (backend/visual.py): what changed, at which width, with
    the approved picture, the new one and the changed pixels in red - for a person to judge, never a bug by itself."""
    if not vis:
        return ""
    c = vis.get("counts") or {}
    head = "<h2>Visual check - the look compared with the approved look</h2>"
    if vis.get("first_run"):
        return (head + f"<p class='muted'>The look of {c.get('new', 0)} page(s), at desktop and phone width, was saved "
                "as the approved look. The next run compares with it.</p>")
    rows = ""
    for p in [p for p in vis.get("pages", []) if p["status"] in ("changed", "approved")][:30]:
        for w, r in (p.get("widths") or {}).items():
            if not r.get("changes"):
                continue
            pics = "".join(f'<div class="vpic">{_img(r.get(k), "vshot")}<span class="muted">{label}</span></div>'
                           for k, label in (("approved_shot", "approved"), ("shot", "now"), ("diff_shot", "changed (red)"))
                           if r.get(k))
            what = "".join(f"<li>{_e(x['detail'])}</li>" for x in r["changes"])
            share = (f"<span class='muted'>{r['percent']}% of the picture changed</span>"
                     if r.get("percent") is not None else "")
            approved = "<br><span class='pill ok'>approved</span>" if p["status"] == "approved" else ""
            rows += (f"<tr><td><b>{_e(p.get('title') or p['url'])}</b><br><span class='url'>{_e(p['key'])}</span>"
                     f"{approved}</td><td>{_e(w)}</td><td><ul>{what}</ul>{share}</td>"
                     f"<td><div class='vpics'>{pics}</div></td></tr>")
    return (head + f"<div class='box'><p>{c.get('compared', 0)} page(s) compared · <b>{c.get('changed', 0)} changed</b> "
            f"(to review) · {c.get('same', 0)} the same · {c.get('new', 0)} new (their look was saved)"
            + (f" · {c['approved']} approved" if c.get("approved") else "") + "</p>"
            "<p class='muted'>A change is shown for a person to judge - a redesign is not a bug. Carousels, ads and "
            "cookie banners are left out, and numbers count as one value. Approve the new look in the app (the report "
            "of this run: 'Approve the new look') or with <code>main.py --approve-visual &lt;run&gt;</code>.</p>"
            + _table(["Page", "Width", "What changed", "Approved · now · changed"], rows, "No page changed its look.")
            + "</div>")


STOP_NAMES = {"run_time_limit": "Run time limit (RUN_TIME_LIMIT_MIN)", "user_stop": "Stopped by you",
              "ctrl_c": "Stopped with Ctrl+C", "error": "The run stopped with an error"}


def limits_hit(state: QAState, run_dir: Path) -> list[dict]:
    """Every limit that stopped or shortened this run, with what it cut - nothing is cut short silently."""
    from .. import cost as cost_mod
    from ..config import settings
    out = []
    if state.get("incomplete"):
        kind = state.get("stop_kind") or "error"
        out.append({"id": kind, "limit": STOP_NAMES.get(kind, STOP_NAMES["error"]),
                    "detail": state.get("incomplete_reason") or "The run did not finish."})
    crawl = state.get("crawl") or {}
    left = crawl.get("not_visited_count", 0)
    if crawl.get("limit_reached") and (crawl.get("visited") or 0) >= (crawl.get("limit") or 0):
        out.append({"id": "page_limit", "limit": "Page limit (MAX_PAGES / HARD_PAGE_CAP)",
                    "detail": f"{left} more page(s) were found but not visited (limit {crawl.get('limit')} pages)."})
    if crawl.get("time_limit_reached"):
        out.append({"id": "crawl_time_limit", "limit": "Crawl time limit (CRAWL_TIME_LIMIT_MIN)",
                    "detail": f"Exploring stopped after {crawl.get('time_limit_min'):g} min: {left} page(s) not visited."})
    if crawl.get("stopped"):
        out.append({"id": "crawl_stopped", "limit": "Exploring stopped early",
                    "detail": f"{crawl['stopped']}: {left} page(s) found but not visited."})
    sections = crawl.get("sections_not_reached") or []
    if sections:  # (the menu's sections come first: one missed means the limit was far too small for this site)
        names = ", ".join(s.rstrip("/").rsplit("/", 1)[-1] or s for s in sections[:10])
        out.append({"id": "sections_not_reached", "limit": "Menu sections not reached",
                    "detail": f"{len(sections)} section(s) of the site's menu were never opened: {names}."})
    vis = _visual(run_dir) or {}
    if vis.get("left_out"):
        out.append({"id": "visual_limit", "limit": "Visual check limit (VISUAL_MAX_PAGES)",
                    "detail": f"{vis['left_out']} page(s) were not compared with their approved look."})
    loading = crawl.get("still_loading") or []
    if loading:  # (a busy server: the page showed, one of its files never came)
        out.append({"id": "still_loading", "limit": "Pages that never finished loading",
                    "detail": f"{len(loading)} page(s) showed but never finished loading (the server never sent one of "
                              f"their files): they were tested as they showed. Run again when the website is less busy."})
    if state.get("cases_left_out"):
        out.append({"id": "test_case_limit", "limit": "Test case limit (MAX_TEST_CASES)",
                    "detail": f"{state['cases_left_out']} designed test case(s) were left out (limit "
                              f"{settings.max_test_cases}; the most important ones were kept)."})
    try:
        execution = json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        execution = {}
    if execution.get("timed_out") or "THE RUN WAS STOPPED BY ITS TIME LIMIT" in " ".join(state.get("log", [])):
        out.append({"id": "suite_timeout", "limit": "Test run time limit (SUITE_TIMEOUT_S)",
                    "detail": f"The tests ran longer than {settings.suite_timeout_s} s: the remaining tests did not run."})
    if execution.get("website_down"):
        d = execution["website_down"]
        out.append({"id": "website_down", "limit": "The website stopped answering",
                    "detail": f"The website did not answer from {d.get('since') or 'some point'} on: {d['tests']} "
                              "test(s) could not run (not failed - nothing is known about them). Run again when it "
                              "is back."})
    if execution.get("stopped"):
        out.append({"id": "execution_stopped", "limit": "Test run stopped early",
                    "detail": "The run was stopped while the tests ran: the tests not finished by then did not run."})
    slow = sum(1 for r in state.get("results", []) if "TestTimeout" in f"{r.get('error_type')} {r.get('error')}")
    if slow:
        out.append({"id": "test_timeout", "limit": "Time limit per test (TEST_TIMEOUT_S)",
                    "detail": f"{slow} test(s) were stopped after {settings.test_timeout_s} s."})
    spent = cost_mod.totals(cost_mod._calls)["cost_usd"]
    if settings.llm_budget_usd and spent >= settings.llm_budget_usd:
        out.append({"id": "ai_budget", "limit": "AI budget (LLM_BUDGET_USD)",
                    "detail": f"${settings.llm_budget_usd:g} was used up: the later AI steps used the built-in rules."})
    return out


def coverage_card(state: QAState, reg: dict | None, m: dict, created: dict, limits: list[dict]) -> dict:
    """ONE card with every coverage number, each with what it counts (Step 12): pages, frames, features by status,
    items per kind, tests, the test data this run created, and the limits that cut the run."""
    rc = (reg or {}).get("counts") or {}
    P, F = rc.get("pages") or {}, rc.get("features") or {}
    frames = [fr for p in state.get("app_map", []) for fr in p.get("frames") or []]
    unsupported = sum(len(p.get("unsupported") or []) for p in state.get("app_map", []))
    kinds = []
    for pattern, t in ((state.get("crawl") or {}).get("item_types") or {}).items():
        smoke = len(t.get("smoke") or [])
        kinds.append({"kind": pattern, "found": t.get("found", 0), "fully_tested": t.get("sampled", 0),
                      "smoke": smoke, "not_reached": max(0, t.get("found", 0) - t.get("sampled", 0) - smoke)})
    st, tc = m.get("single_tests") or {}, m.get("test_cases") or {}
    return {
        "pages": {"found": P.get("discovered", 0), "inspected": P.get("inspected", 0), "tested": P.get("tested", 0),
                  "verified": P.get("verified", 0), "not_reached": P.get("not_reached", 0)},
        "frames": {"testable": sum(1 for f in frames if f.get("status") == "testable"),
                   "external": sum(1 for f in frames if f.get("status") == "external"),
                   "unreachable": sum(1 for f in frames if f.get("status") == "unreachable")},
        "features": {"found": F.get("discovered", 0), "verified": F.get("verified", 0), "failed": F.get("failed", 0),
                     "smoke_only": F.get("smoke", 0), "suspect": F.get("suspect", 0),
                     "rule_violation": F.get("rule_violation", 0), "inconclusive": F.get("inconclusive", 0),
                     "blocked": F.get("blocked", 0), "unsupported": unsupported,
                     "needs_login": F.get("needs_login", 0),
                     "not_tested": F.get("unresolved", 0) + F.get("test_generated", 0) + F.get("skipped", 0)
                     + F.get("clicked_only", 0)},
        "items": kinds,
        "tests": {"single_tests": st.get("total", 0), "test_cases_planned": tc.get("planned", 0),
                  "test_cases_executed": tc.get("executed", 0)},
        "data": {"created": created.get("created", 0), "cleaned": created.get("deleted", 0),
                 "left": len(created.get("left") or [])},
        "limits_hit": [x["limit"] for x in limits],
    }


def _js_html(js: dict | None) -> str:
    if not js or js.get("percent") is None:
        return ""
    least = "".join(f"<li>{_e(x['script'])}: {x['percent']}% of {x['bytes']:,} bytes</li>" for x in js["least_used"][:6])
    return (f"<p><b>JavaScript:</b> the run executed <b>{js['percent']}%</b> of the website's own JavaScript "
            f"({js['own_scripts']} script(s), {js['own_bytes']:,} bytes; {js['other_scripts']} script(s) of other "
            "websites not counted).</p>"
            + (f"<p class='muted'>The least used of its scripts - each may hold features no test reached:</p>"
               f"<ul>{least}</ul>" if least else ""))


def _card_html(card: dict) -> str:
    def row(label: str, parts: dict) -> str:
        return (f"<tr><th>{_e(label)}</th><td>" + " · ".join(f"<b>{v}</b> {_e(k.replace('_', ' '))}"
                                                           for k, v in parts.items()) + "</td></tr>")
    items = "".join(f"<li>{_e(k['kind'])}: <b>{k['fully_tested']}</b> fully tested, <b>{k['smoke']}</b> smoke-checked, "
                    f"<b>{k['found']}</b> found" + (f", {k['not_reached']} not reached" if k.get("not_reached") else "")
                    + "</li>" for k in card["items"][:12])
    return (f'<h2>Coverage card</h2><div class="box"><table>{row("Pages", card["pages"])}{row("Frames", card["frames"])}'
            f'{row("Features", card["features"])}{row("Tests", card["tests"])}{row("Test data (staging)", card["data"])}'
            f'</table>' + (f"<h4>Items per kind (address pattern)</h4><ul>{items}</ul>" if items else "")
            + (f"<p><b>Limits hit:</b> {_e(', '.join(card['limits_hit']))}</p>" if card["limits_hit"] else "")
            + _js_html(card.get("javascript"))
            + '<p class="muted">Smoke only = its test passed, but only checked that nothing broke; suspect = it did '
              'nothing (a person should look); rule violation = a common rule between fields not kept (a question); '
              'unsupported = its content can\'t be read (a closed shadow root).</p></div>')


def _roles_html(state: QAState, cases: list[dict]) -> str:
    """Several user roles: a role x page table - what each role may open while exploring, and its test's result."""
    rm = state.get("roles") or {}
    roles = rm.get("roles") or {}
    if not roles:
        return ""
    names = [rm.get("main") or "test account"] + list(roles)
    result = {(c["spec"]["role"], c["spec"]["url"]): c.get("execution_status") for c in cases if c.get("kind") == "role"}
    mark = {"ok": "✓ opens", "denied": "✗ refused", "login": "→ login page", "redirected": "→ sent away",
            "error": "? error"}
    rows = ""
    for p in [p for p in state.get("app_map", []) if p.get("roles")][:60]:
        cells = ""
        for r in names:
            access = (p.get("roles") or {}).get(r)
            res = result.get((r, p["url"]))
            cells += (f"<td>{_e(mark.get(access, '-'))}" + (f" <span class='muted'>({_e(res)})</span>" if res else "")
                      + "</td>")
        rows += f"<tr><td class='url'>{_e(p['url'])}</td>{cells}</tr>"
    no_login = [f"{r}: {v.get('login')}" for r, v in roles.items() if v.get("login") != "success"]
    return ("<h2>User roles - who may open what</h2><div class=\"box\">"
            + _table(["Page"] + names, rows, "No pages behind the login.")
            + (f"<p class='muted'>Could not sign in: {_e(', '.join(no_login))}</p>" if no_login else "")
            + "<p class='muted'>From exploring with each role's own test account; the result in brackets is its test "
              "now (a lower role must stay refused).</p></div>")


def vision_html(state: QAState, cases: list[dict]) -> tuple[str, dict]:
    """What the AI saw on the screenshots (backend/vision.py): every page's features - and the ones no test case of
    that page names (seen on screen, not tested) - and its verdict on each failed test it looked at."""
    from ..vision import coverage
    app_map, results = state.get("app_map", []), state.get("results", [])
    looked = [p for p in app_map if p.get("seen")]
    verdicts = Counter((r.get("vision") or {}).get("verdict") for r in results if r.get("vision"))
    summary = {"pages_looked_at": len(looked), "features_seen": sum(len(p["seen"].get("features", [])) for p in looked),
               "failed_tests_looked_at": sum(verdicts.values()),
               "website_bug": verdicts["website_bug"], "test_mistake": verdicts["test_mistake"],
               "cannot_tell": verdicts["cannot_tell"]}
    if not looked and not verdicts:
        return "", summary
    gaps = coverage(app_map, cases)
    summary["seen_not_tested"] = sum(len(v) for v in gaps.values())
    rows = "".join(
        f"<tr><td class='url'>{_e(p['url'])}</td><td>{_e(p['seen'].get('purpose') or '')}</td>"
        f"<td>{_e(', '.join(f['name'] for f in p['seen'].get('features', [])[:12]))}</td>"
        f"<td>{_e(', '.join(f['name'] + ' (' + f['kind'] + ')' for f in gaps.get(p['url'], [])[:8])) or '-'}</td></tr>"
        for p in looked[:60])
    return (f"<h2>What the AI saw on the screen</h2><div class='box'><p>The AI looked at <b>{len(looked)}</b> page "
            f"picture(s) and saw <b>{summary['features_seen']}</b> feature(s); <b>{summary.get('seen_not_tested', 0)}"
            f"</b> of them are not named by any test case of their page (column 4: check those by hand). It looked at "
            f"<b>{summary['failed_tests_looked_at']}</b> failed test(s): {verdicts['test_mistake']} test mistake(s) "
            f"(the website did the right thing), {verdicts['website_bug']} looked like a website bug, "
            f"{verdicts['cannot_tell']} could not be told from the pictures.</p>"
            + _table(["Page", "What it is for", "Features seen", "Seen on screen, not tested"], rows, "")
            + "<p class='muted'>Pages with a password box are never sent to the AI. Its verdict on a failed test "
              "is shown with the finding ('The AI looked at the screenshots: ...').</p></div>"), summary


def created_records(run_dir: Path) -> dict:
    """What a staging run created (runs/<run>/created.jsonl, written by the tests): each tag's last status -> created
    / deleted / left for manual cleanup. Saved as created.json."""
    f = run_dir / "created.jsonl"
    latest = {}
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            first = latest.get(r["tag"], {}).get("first_seen") or r.get("time")
            latest[r["tag"]] = dict(r, first_seen=first)
    records = list(latest.values())
    out = {"created": len(records), "deleted": sum(1 for r in records if r["status"] == "deleted"),
           "left": [r for r in records if r["status"] != "deleted"], "records": records}
    if records:
        (run_dir / "created.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def reporter_agent(state: QAState) -> QAState:
    if state.get("discovery_only"):
        from ..discovery_report import discovery_report
        return discovery_report(state)
    if state.get("target_type") == "mobile":
        from ..android_reporting import report
        return report(state)
    run_dir = Path(state["run_dir"])
    from .failure_analysis import ensure_findings_from_results, load_saved_results
    app_map = state.get("app_map", [])
    results = list(state.get("results") or [])
    disk_results = load_saved_results(run_dir)
    if len(disk_results) > len(results):
        results = disk_results  # interrupt/timeout: jsonl may be ahead of in-memory state
    cases = state.get("test_cases", [])
    if not cases and (run_dir / "test_cases.json").exists():
        try:
            loaded = json.loads((run_dir / "test_cases.json").read_text(encoding="utf-8"))
            cases = loaded if isinstance(loaded, list) else []
        except (OSError, ValueError, TypeError):
            cases = []
    # Gates/metrics must see a finding for every failed/inconclusive result (LLM optional).
    failures = ensure_findings_from_results(
        run_dir, results, cases=cases, app_map=app_map,
        unhealable=state.get("unhealable"), healing_log=state.get("healing_log"))
    state = dict(state, results=results, failures=failures, test_cases=cases)
    failures = sorted(failures, key=lambda f: SEV_ORDER.get(f.get("severity"), 9))
    fill_case_results(cases, results, failures, run_dir / "generated_tests")  # results + evidence of every case
    from .. import registry  # every feature's final status (verified / failed / ... + why) and the counts
    reg = registry.load(run_dir)
    from .. import assert_strength  # how strong each test's proof is (a passed weak test is only "smoke")
    strength = assert_strength.save(run_dir) if (run_dir / "generated_tests").exists() else {}
    if reg:  # (before the verdict: the feature coverage gate compares the registry with what was tested)
        registry.record_outcomes(reg, cases, state.get("crawl"), results, strength)
        registry.save(reg, run_dir)
        state = dict(state, feature_counts=reg["counts"])
    verdict, reasons, gates = decide_verdict(state)
    # ONE calculation of every number the report, the summary, the chat and Excel show - checked against each other
    from .. import metrics as metrics_mod
    m = metrics_mod.build(results, cases, reg, failures, state.get("crawl"), run_dir / "generated_tests")
    (run_dir / "metrics.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    # Consistency errors must lead the summary reasons whenever totals do not add up.
    reasons = consistency_reasons(m) + list(reasons)
    if not m.get("consistent", True) and verdict == "Ready":
        verdict = "Ready with Risks"
    st = m["single_tests"]
    passed, skipped, unclear, failed = st["passed"], st["skipped"], st["inconclusive"], st["failed"]
    fixes = build_fixes(state)
    comparison = compare_with_previous(state, run_dir, cases)
    (run_dir / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    (run_dir / "test_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    cov3 = coverage_summary(state, run_dir)
    if reg:
        cov3["registry"] = reg["counts"]
    cost = write_cost_report(run_dir, cases, results)  # after build_fixes: its AI calls are counted too
    if cases:
        write_workbook(run_dir, cases, results, cost, m)
    print(f"  [cost] AI cost for this run: {fmt_usd(cost['cost_usd'])} "
          f"({cost['calls']} calls, {cost['tokens_in'] + cost['tokens_out']} tokens) - "
          f"{fmt_usd(cost['avg_cost_per_case_usd'])} per test case")

    limits = limits_hit(state, run_dir)
    from ..report_clarity import build as clarity_build
    clarity = clarity_build(
        crawl=state.get("crawl"), app_map=app_map, limits=limits,
        incomplete=bool(state.get("incomplete")), discovery_only=False,
        test_cases=m.get("test_cases"), cases=cases, feature_counts=state.get("feature_counts") or (
            (reg or {}).get("counts") if reg else None))
    story = headline(verdict, fixes, reasons, partial_coverage=clarity["coverage_limitations"]["partial"])
    good = working_well(app_map, results, cases, m)
    confidence = coverage_confidence(cov3, state, limits)
    vis = _visual(run_dir)  # (the visual check: its own section - a change of the look is no failure)
    limits_html = ""
    if limits:  # (an unfinished run says so first: what was not reached is not tested - never counted as passed)
        incomplete = bool(state.get("incomplete"))
        limits_html = (f'<div class="box" style="margin-top:14px;border-left:4px solid {COLORS["Ready with Risks"]}">'
                       f'<h3>{"⚠️ This run is incomplete" if incomplete else "Limits hit in this run"}</h3>'
                       + ('<p>The report shows everything done until the run stopped. What was not reached is not '
                          'tested, and it is not counted as passed.</p>' if incomplete else '')
                       + "<ul>" + "".join(f"<li><b>{_e(x['limit'])}</b> - {_e(x['detail'])}</li>" for x in limits)
                       + "</ul></div>")
    from ..config import settings as cfg
    created = created_records(run_dir)
    if created["created"] or cfg.writes_note:  # what this run changed on the website (staging) - or why nothing
        left = "".join(f"<li>{_e(r['tag'])} ({_e(r['where'])})</li>" for r in created["left"][:20])
        limits_html += (f'<div class="box" style="margin-top:14px"><h3>Data this run changed</h3>'
                        f'<p>{_e(cfg.writes_note)}</p>'
                        + (f"<p>{created['created']} record(s) created with the run's tag, {created['deleted']} "
                           f"deleted again, <b>{len(created['left'])} left for manual cleanup</b>.</p>"
                           if created["created"] else "")
                           + (f"<ul>{left}</ul>" if left else "") + "</div>")
    card = coverage_card(state, reg, m, created, limits)
    from urllib.parse import urlparse as _up

    from .. import jscov  # how much of the website's own JavaScript the crawl and the tests ran (Chromium)
    card["javascript"] = jscov.summary(run_dir, _up(state.get("url") or "").hostname or "")
    limits_html += _card_html(card) + _roles_html(state, cases)
    heals = state.get("healing_log", [])
    color = COLORS[verdict]
    # the headline rate: FUNCTIONAL test cases that passed, of those with a verdict (link / page / input checks have
    # their own rates and never inflate it - see metrics.py)
    head = m["headline"]
    pass_rate = head["percent"] if head["percent"] is not None else 0
    total = max(1, len(results))
    used_ai = cost["provider"] not in ("none", "") and cost["calls"]
    by_prio = {k: sum(1 for x in fixes if x["priority"] == k) for k in ("critical", "high", "medium", "low")}

    # ---- what to fix, step by step
    fix_cards = "".join(f"""
    <article class="fix p-{_e(x['priority'])}">
      <div class="num">{n}</div>
      <div class="fbody">
        <div class="ftop"><span class="chip">{_e(PRIORITY_WORDS.get(x['priority'], x['priority']))}</span>
          <h3>{_e(x['title'])}</h3>{f'<span class="muted">× {x["count"]}</span>' if x['count'] > 1 else ''}</div>
        {f'<a class="where" href="{_e(x["where"])}" target="_blank">{_e(x["where"])}</a>' if str(x['where']).startswith('http') else f'<span class="where">{_e(x["where"])}</span>'}
        <p class="why"><b>Why it matters:</b> {_e(x.get('why', ''))}</p>
        <p class="how"><b>How to fix:</b> {_e(x['fix'])}{' <span class="muted">(advice by AI)</span>' if x['source'] == 'ai' else ''}</p>
        {_code_html(x.get('code'))}
      </div>
      {_img(x.get('screenshot'), 'fshot')}
    </article>""" for n, x in enumerate(fixes, start=1))

    # ---- page by page
    titles = {t: c["title"] for c in cases for t in c.get("tests") or [f"test_{_ident(c['id'])}"] if not t.endswith("*")}
    flow_pages = {t: c.get("pages") or [] for c in cases if c.get("kind") in ("flow", "journey", "check", "feature")
                  for t in c.get("tests") or []}

    def page_card(p: dict) -> str:
        slug = p["slug"]
        files = {f"test_{_ident(slug)}{s}.py" for s in ("", "_added", "_data")}
        rs = [r for r in results if r["file"] in files                                         # its input-box checks
              or (r["file"] == "test_site.py" and r["test"].endswith(f"[{_ident(slug)}]"))     # opens / no errors / pictures
              or slug in flow_pages.get(r["test"].split("[")[0], [])]                          # large cases visiting it
        ok = sum(r["outcome"] == "passed" for r in rs)
        bad = [r for r in rs if r["outcome"] in ("failed", "error")]
        broken = not page_testable(p)
        bad_list = "".join(f'<li>{_e(titles.get(r["test"].split("[")[0], r["test"]))}</li>' for r in bad[:5])
        return f"""
      <div class="page {'pbad' if broken or bad else ''}">
        {_img(p.get('screenshot'), 'pshot') or '<div class="pshot none">no screenshot</div>'}
        <div class="pcap"><b title="{_e(p.get('title'))}">{_e(p.get('title') or '(no title)')}</b>
          <a class="url" href="{_e(p['url'])}" target="_blank">{_e(p['url'])}</a>
          <div class="pstats">{'<span class="pill bad">page does not open</span>' if broken else ''}
            {f'<span class="pill">found by: {_e(p["found_by"])}</span>' if p.get("found_by") not in (None, "link", "start") else ''}
            <span class="pill ok">✓ {ok} passed</span>{f'<span class="pill bad">✗ {len(bad)} failed</span>' if bad else ''}</div>
          {f'<ul class="fails">{bad_list}</ul>' if bad_list else ''}
        </div>
      </div>"""

    page_cards = "".join(page_card(p) for p in app_map)

    # ---- details (folded): frontend changes, self-healing, cost, all results, log
    ch = state.get("changes") or {}
    if not ch:
        changes_html = '<p class="muted">Not available.</p>'
    elif ch.get("first_run"):
        changes_html = ('<p class="muted">This was the first test of this website, so there is nothing to compare yet. '
                        'Next time, this section shows which pages are new, changed or removed.</p>')
    else:
        rows = "".join(f'<tr><td><span class="pill ok">new</span></td><td class="url">{_e(u)}</td><td>New page - tests written</td></tr>'
                       for u in ch.get("new", []))
        rows += "".join(f'<tr><td><span class="pill warn">changed</span></td><td class="url">{_e(c["url"])}</td>'
                        f'<td><ul>{"".join(f"<li>{_e(d)}</li>" for d in c["details"])}</ul></td></tr>'
                        for c in ch.get("changed", []))
        rows += "".join(f'<tr><td><span class="pill">removed</span></td><td class="url">{_e(u)}</td><td>Page no longer found</td></tr>'
                        for u in ch.get("removed", []))
        changes_html = (f'<p class="muted">Compared with the test of {_e(ch.get("baseline_date"))}: '
                        f'{len(ch.get("new", []))} new, {len(ch.get("changed", []))} changed, '
                        f'{len(ch.get("unchanged", []))} unchanged, {len(ch.get("removed", []))} removed pages.</p>'
                        + _table(["Status", "Page", "What changed"], rows, "No frontend changes."))

    def heal_evidence(h: dict) -> str:  # what running it again showed - a repair is only kept on that evidence
        rr = h.get("rerun") or {}
        parts = ([f"ran again: <b>{_e(rr.get('outcome'))}</b>" + (f" ({_e(rr['category'])})" if rr.get("category") else "")]
                 if rr else [])
        if h.get("related"):
            parts.append(f"{len(h['related'])} other test(s) of the file ran again too")
        if h.get("why"):
            parts.append(_e(h["why"]))
        if h.get("backup"):
            parts.append(f'script before the repair: <a href="{_e(h["backup"])}">{_e(h["backup"])}</a>')
        return f'<div class="muted">{" · ".join(parts)}</div>' if parts else ""

    heal_rows = "".join(f"""
      <tr><td>{'<span class="pill ok">' + _e(h['status']) + '</span>' if h['status'] in ('healed', 'repaired') else '<span class="pill bad">' + _e(h['status']) + '</span>'}</td>
        <td>{_e(h['file'])}<br><span class="muted">{_e(h['test'])} · round {h['round']} · {_e(h.get('method') or '-')}</span></td>
        <td><b>{_e(h.get('change'))}</b>{heal_evidence(h)}{f'<pre>{_e(h["diff"])}</pre>' if h.get('diff') else ''}</td></tr>""" for h in heals)

    agent_rows = "".join(f"<tr><td>{_e(a.replace('_', ' '))}</td><td>{t['calls']}</td><td>{t['tokens_in'] + t['tokens_out']}</td>"
                         f"<td>{_e(fmt_usd(t['cost_usd']))}</td></tr>" for a, t in cost["by_agent"].items())
    case_cost_rows = "".join(f"<tr><td>{_e(c['title'] or c['id'])}<br><span class='muted'>{_e(c['page'])}</span></td>"
                             f"<td>{c['tokens']}</td><td>{_e(fmt_usd(c['cost_usd']))}</td><td>{c['exec_s']} s</td></tr>"
                             for c in sorted(cost["per_case"], key=lambda c: -c["cost_usd"])[:30])
    cost_html = (f"""<p>AI: <b>{_e(cost['provider'])} {_e(cost['model'])}</b> · total <b>{_e(fmt_usd(cost['cost_usd']))}</b>
        · <b>{_e(fmt_usd(cost['avg_cost_per_case_usd']))}</b> per test case · {cost['calls']} AI calls ·
        {cost['tokens_in'] + cost['tokens_out']} tokens · whole run {cost['run_seconds']} s</p>
        <p class="muted">{_e(cost['note'])}</p>"""
                 + _table(["Agent", "AI calls", "Tokens", "Cost"], agent_rows, "No AI calls.")
                 + "<h4>Cost per test case</h4>"
                 + _table(["Test case", "Tokens", "AI cost", "Run time"], case_cost_rows, "No test cases."))

    def evidence_links(r: dict) -> str:
        return " ".join(f'<a href="{_e(r[k])}" target="_blank">{label}</a>'
                        for k, label in (("screenshot", "screenshot"), ("trace", "trace")) if r.get(k))

    def steps_of(r: dict) -> str:  # (every step the test did, in order - the failing one marked ✗)
        steps = r.get("live_steps") or []
        if not steps:
            return ""
        items = "".join(f"<li style='color:{'var(--bad)' if s.get('ok') is False else 'inherit'}'>"
                        f"{'✗' if s.get('ok') is False else '✓' if s.get('ok') else '·'} {_e(s.get('text'))}</li>"
                        for s in steps)
        return (f"<details{' open' if r['outcome'] in ('failed', 'error') else ''}><summary>{len(steps)} step(s)"
                f"</summary><ol style='margin:4px 0 0 18px;font-size:12px'>{items}</ol></details>")

    result_rows = "".join(f"""
      <tr><td>{'✅' if r['outcome'] == 'passed' else '⏭️' if r['outcome'] == 'skipped' else '❔' if r['outcome'] == 'inconclusive' else ('⚠️' if r.get('flaky') else '❌')}</td>
        <td><a href="generated_tests/{_e(r['file'])}" target="_blank">{_e(r['file'])}</a></td>
        <td>{_e(r['test'])}{steps_of(r)}</td><td>{_e(r['outcome'])}{' (flaky)' if r.get('flaky') else ''}{' (after healing)' if r.get('healed_round') else ''}</td>
        <td>{_e(r.get('checks', ''))}</td><td>{_e(r['duration_s'])} s</td><td>{evidence_links(r)}</td></tr>""" for r in results)

    # ---- the numbers: every total from ONE calculation (metrics.json), each percentage with its denominator,
    # and the checks that the totals add up
    rate_rows = "".join(f"<tr><td><b>{_e(r['name'])}</b></td><td>{r['passed']} / {r['of']}</td>"
                        f"<td>{'' if r['percent'] is None else str(r['percent']) + '%'}</td>"
                        f"<td class='muted'>{_e(r['denominator'])}</td></tr>" for r in m["rates"])
    group_rows = "".join(f"<tr><td>{_e(g['label'])}</td><td>{g['total']}</td><td>{g['passed']}</td><td>{g['failed']}</td>"
                         f"<td>{g['skipped']}</td><td>{g['inconclusive']}</td><td>{g['assertions']}</td></tr>"
                         for g in st["groups"].values())
    tcm, wf, fd = m["test_cases"], m["workflows"], m["findings"]
    wf_rows = "".join(f"<li>{_e(w['status'])} - {_e(w['title'])}"
                      + (f"<br><span class='muted'>verified: {_e(' · '.join(w['steps_verified']))}</span>"
                         if w["steps_verified"] else "") + "</li>" for w in wf["list"])
    check_rows = "".join(f"<tr><td>{'✓' if c['ok'] else '✗'}</td><td>{_e(c['check'])}</td><td class='muted'>"
                         f"{_e(c['detail'])}</td></tr>" for c in m["consistency"])
    numbers_html = f"""<h2>The numbers - one calculation, every denominator said</h2>
<div class="box">
{_table(["Rate", "Passed / of", "%", "Counted (the denominator)"], rate_rows, "")}
<h4>Test cases (designed: one test case can run several single tests)</h4>
<p>{tcm['planned']} planned · {tcm['executed']} executed · <b>{tcm['passed']} passed</b> · <b>{tcm['failed']} failed</b>
  · {tcm['flaky']} flaky · {tcm['inconclusive']} inconclusive · {tcm['skipped']} skipped · {tcm['blocked']} blocked
  (protected) · {tcm['not_run'] + tcm['pending']} not run</p>
<h4>Single tests (what pytest ran) and the assertions they executed</h4>
{_table(["Group", "Ran", "Passed", "Failed", "Skipped", "Inconclusive", "Assertions"], group_rows, "No tests ran.")}
<h4>End-to-end workflows</h4>
{f'<ul>{wf_rows}</ul>' if wf_rows else '<p class="muted">No end-to-end workflow was found to test.</p>'}
<h4>Findings: application defects vs. test-script problems</h4>
<p>{fd['application_defects']} application defect(s) · {fd['test_problems']} test-script / locator / environment
  problem(s) · {fd['to_review']} expectation(s) to review · {fd['auth_or_data']} login / test-data problem(s) ·
  {fd['inconclusive']} inconclusive · {fd['seen_while_crawling']} issue(s) seen while crawling</p>
<h4>Consistency checks - do the totals add up?</h4>
{_table(["", "Check", "Details"], check_rows, "")}
</div>"""

    # ---- release gates (how the verdict was calculated)
    icon = {"pass": ("✓ pass", "ok"), "fail": ("✗ fail", "bad"), "missing": ("? no evidence", "warn"), "risk": ("! risk", "warn")}
    gate_rows = "".join(f"<tr><td><span class='pill {icon[g['status']][1]}'>{icon[g['status']][0]}</span></td>"
                        f"<td><b>{_e(g['name'])}</b>{'' if g['mandatory'] else ' <span class=muted>(not mandatory)</span>'}"
                        f"</td><td>{_e(g['detail'])}</td></tr>" for g in gates)
    gates_html = ("<h2>Release gates</h2><div class='box'><p class='muted'>The verdict is calculated from these fixed "
                  "rules (thresholds in .env: GATE_*). The AI only looks at the screenshots of failed tests: it can "
                  "mark a failure as a test mistake (the website did the right thing) or ask a person to confirm a "
                  "possible bug - it never makes a website bug on its own.</p>"
                  + _table(["Status", "Gate", "Details"], gate_rows, "") + "</div>")

    # ---- three separate coverages
    R, C, X, P, F = cov3["routes"], cov3["components"], cov3["execution"], cov3["pages"], cov3["features"]
    skipped_why = ", ".join(f"{n} × {why}" for why, n in R["skipped_reasons"].items())
    journey_rows = "".join(f"<li>{_e(j['status'])} - {_e(j['title'])}</li>" for j in cov3["journeys"])
    blocked_rows = "".join(f"<li>⛔ {_e(b['title'])}</li>" for b in cov3["blocked"][:20])
    conf_reasons = "".join(f"<li>{_e(x)}</li>" for x in confidence["reasons"])
    conf_next = "".join(f"<li>{_e(x)}</li>" for x in confidence["next_steps"])
    cr = confidence["rates"]
    confidence_html = f"""<h2>Coverage confidence</h2>
<div class="box">
  <div class="nums">
    <div class="n {'ok' if confidence['label'] == 'High' else 'warn' if confidence['label'] == 'Medium' else 'bad'}">
      <b>{_e(confidence['label'])}</b><span>confidence ({confidence['score']} / 100)</span></div>
    <div class="n"><b>{cr['routes']}%</b><span>route coverage</span></div>
    <div class="n"><b>{cr['controls']}%</b><span>control coverage</span></div>
    <div class="n"><b>{cr['execution']}%</b><span>execution coverage</span></div>
  </div>
  <p>{_e(confidence['summary'])}</p>
  <h4>Why</h4><ul>{conf_reasons}</ul>
  <h4>Best next steps</h4><ul>{conf_next}</ul>
</div>"""
    coverage3_html = f"""<h2>Coverage - discovered, inspected, tested, verified</h2>
<div class="nums">
  <div class="n"><b>{P['discovered']}</b><span>pages discovered</span></div>
  <div class="n"><b>{P['inspected']}</b><span>pages inspected (opened, every control read)</span></div>
  <div class="n"><b>{P['tested']}</b><span>pages tested (a test ran on them)</span></div>
  <div class="n ok"><b>{P['verified']}</b><span>pages verified (a test passed on them)</span></div>
</div>
<div class="nums">
  <div class="n"><b>{R['visited']} / {R['found']}</b><span>pages visited / found (route coverage){' - STOPPED AT THE PAGE LIMIT' if R['limit_reached'] else ''}{' - STOPPED AT THE TIME LIMIT' if P['time_limit_reached'] else ''}</span></div>
  <div class="n"><b>{C['tested']} / {C['found']}</b><span>controls used by a test / found (component coverage)</span></div>
  <div class="n"><b>{X['executed']} / {X['cases']}</b><span>test cases executed / designed (execution coverage)</span></div>
  <div class="n"><b>{F['passed']} / {F['tests']}</b><span>feature tests passed / designed ({F['found']} features found)</span></div>
</div>
<div class="box" style="margin-top:12px"><ul>
  <li>Pages behind the login inspected: <b>{P['logged_in']}</b> · not reached because they need a test account (a
    visitor is sent to the login page): <b>{len((state.get('crawl') or {}).get('needs_login') or [])}</b>
    {_e(', '.join(x['url'].split('//', 1)[-1].split('/', 1)[-1] for x in ((state.get('crawl') or {}).get('needs_login') or [])[:6]))}
    · needing other permissions: <b>{P['needs_permission']}</b>
    · could not open: <b>{max(0, P['could_not_open'])}</b> · sampled (same address pattern): <b>{P['sampled']}</b></li>
  <li>Page types: {_e(', '.join(f'{n} {t}' for t, n in P['types'].items()))}</li>
  <li>Pages found but not visited because of the page limit ({_e(R['limit'])}): <b>{R['not_visited_limit']}</b></li>
  <li>Links skipped on purpose: <b>{R['skipped']}</b>{f' ({_e(skipped_why)})' if skipped_why else ''}</li>
  <li>Redirects outside the approved website (not tested): <b>{R['redirected_out']}</b> · requests blocked by the safety
    rules: <b>{R['blocked_requests']}</b> · links to other websites: <b>{R['external_links']}</b></li>
  <li>Test cases: {X['automated']} automated · {X['passed']} passed · {X['failed']} failed · {X['flaky']} flaky ·
    {X['skipped']} skipped · {X['blocked']} blocked · {X['inconclusive']} inconclusive · {X['not_run']} not run</li>
</ul>{f'<h4>User journeys</h4><ul>{journey_rows}</ul>' if journey_rows else ''}
{f'<h4>Blocked - protected actions that need approval</h4><ul>{blocked_rows}</ul>' if blocked_rows else ''}
<p class="muted">An empty list of pages to visit does not mean the whole website was tested: pages that need other
permissions, pages beyond the limits and protected actions are listed above.</p></div>""" + registry_html(run_dir, state)
    seen_html, seen_summary = vision_html(state, cases)
    coverage3_html += seen_html

    # ---- regression: compared with the last run of this website
    if comparison.get("previous_run"):
        changed = [r for r in comparison["cases"] if r["change"] != "unchanged"]
        crow = "".join(f"<tr><td><span class='pill {'bad' if r['change'] in ('newly failing', 'still failing') else 'ok' if r['change'] == 'fixed' else ''}'>"
                       f"{_e(r['change'])}</span></td><td>{_e(r['tc_id'])}</td><td>{_e(r['title'])}</td>"
                       f"<td>{_e(r['before'] or '-')} → {_e(r['after'] or '-')}</td></tr>" for r in changed)
        compare_html = (f"<h2>Compared with the last run</h2><div class='box'><p>Previous run: <b>{_e(comparison['previous_run'])}</b> "
                        f"(verdict: {_e(comparison['previous_verdict'])}) · "
                        + " · ".join(f"{n} {_e(k)}" for k, n in comparison["counts"].items()) + "</p>"
                        + _table(["Change", "Test ID", "Test case", "Before → now"], crow, "No test case changed its result.")
                        + "</div>")
    else:
        compare_html = ("<h2>Compared with the last run</h2><p class='muted'>This is the first finished run of this website, "
                        "so there is nothing to compare yet. Next time (or with “Run the same tests again”) this section "
                        "shows which test cases started failing, were fixed or still fail.</p>")

    # ---- bug reports for the suspected website bugs
    bugs = [f for f in failures if f.get("bug")]
    bug_html = "".join(f"""<div class="box" style="margin-bottom:10px"><h3>{_e(b['bug']['title'])}</h3>
      <p class="muted">{_e(b.get('tc_id') or '')} · route {_e(b['bug']['route'])} · {_e(b['bug']['feature'])} ·
        severity <b>{_e(b['severity'])}</b> · confidence <b>{_e(b['confidence'])}</b></p>
      <p><b>Steps to reproduce:</b></p><ol>{''.join(f'<li>{_e(s)}</li>' for s in b['bug']['steps'])}</ol>
      <p><b>Expected:</b> {_e(b['bug']['expected'])}</p><p><b>Actual:</b></p><pre>{_e(b['bug']['actual'])}</pre>
      <p><b>Evidence:</b> {' · '.join(f'<a href="{_e(x)}" target="_blank">{_e(x)}</a>' if '/' in str(x) else _e(x) for x in b.get('evidence') or []) or 'none'}</p>
      <p><b>Next:</b> {_e(b.get('next_action'))}{f' <span class="muted">· AI: {_e(b["ai_explanation"])}</span>' if b.get('ai_explanation') else ''}</p></div>"""
                       for b in bugs)

    finding_rows = "".join(f"""
      <tr><td><span class="pill {'bad' if f['severity'] in ('critical', 'high') else 'warn'}">{_e(f['severity'])}</span>
          <br><span class="muted">confidence {_e(f.get('confidence', '-'))}</span></td>
        <td><b>{_e(f.get('category_name') or f['category'].replace('_', ' '))}</b><br><span class="muted">{_e(f['source'])}: {_e(f['test'])}</span>
          {f'<br><span class="muted">AI suggests: {_e(f["ai_suggested_category"])}</span>' if f.get('ai_suggested_category') else ''}</td>
        <td class="url">{_e(f['page_url'])}</td><td>{_e(f['explanation'])}<pre>{_e(f['error'])}</pre>
          {' '.join(f'<a href="{_e(x)}" target="_blank">{"trace" if str(x).endswith(".zip") else "screenshot"}</a>' for x in (f.get('screenshot'), f.get('trace')) if x)}</td></tr>""" for f in failures)

    # coverage: what was found on the pages, and what was NOT tested (and why) - nothing is skipped silently
    cov = json.loads((run_dir / "coverage.json").read_text(encoding="utf-8")) if (run_dir / "coverage.json").exists() else None
    if cov and cov["total"]:
        missed = [(p["url"], i) for p in cov["pages"] for i in p["items"] if i["status"] != "tested"]
        missed_rows = "".join(f"<tr><td>{_e(i['name'])}</td><td>{_e(i['kind'])}</td><td class='url'>{_e(u)}</td>"
                              f"<td>{_e(i['reason'])}</td></tr>" for u, i in missed)
        coverage_html = (f"<h2>What was tested</h2><div class='box'><p><b>{cov['tested']} of {cov['total']}</b> controls "
                         f"found on the pages were tested.</p>"
                         + "".join(f"<p class='warn'>⚠ {_e(n)}</p>" for n in cov.get("notes") or [])
                         + (_table(["Not tested", "Kind", "Page", "Why"], missed_rows, "") if missed
                            else "<p>Every control that was found was tested. ✅</p>") + "</div>")
    else:
        coverage_html = ""

    proj = state.get("project")
    log_items = "".join(f"<li>{_e(l)}</li>" for l in state.get("log", []))
    pct = lambda n: f"{100 * n / total:.1f}%"  # noqa: E731

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test report — {_e(state.get('source') or state['url'])}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Manrope:wght@400;500;600;700&display=swap">
<style>
:root {{ --bg:#f6f7fb; --fg:#171a2b; --card:#fff; --muted:#6b7084; --line:#e6e8f0; --soft:#f2f3f8;
  --ok:#16a34a; --okbg:#e8f7ee; --bad:#dc2626; --badbg:#fdecec; --warn:#d97706; --warnbg:#fff4e0; --accent:#5b5bf0;
  --v:{color}; --shadow:0 1px 2px rgba(20,22,40,.05),0 10px 30px -14px rgba(20,22,40,.22); }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0f1117; --fg:#e9ebf5; --card:#171a23; --muted:#9298ad; --line:#262a37;
  --soft:#1d2130; --okbg:#12301f; --badbg:#3a1717; --warnbg:#352710; --ok:#4ade80; --bad:#f87171; --warn:#fbbf24; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; font:15px/1.6 Manrope,system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--bg); color:var(--fg); }}
main {{ max-width:1080px; margin:0 auto; padding:28px 18px 80px; }}
a {{ color:var(--accent) }} .muted {{ color:var(--muted) }} .url {{ word-break:break-all; font-size:12.5px }}
.brand {{ font-size:13px; color:var(--muted); display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px }}
.brand b {{ color:var(--fg) }}
h2 {{ font-size:20px; margin:42px 0 14px; letter-spacing:-.01em }}
h3 {{ margin:0; font-size:16px }} h4 {{ margin:18px 0 8px; font-size:14px }}
.hero {{ margin-top:14px; border-radius:22px; padding:28px; color:#fff; display:grid; grid-template-columns:1fr auto; gap:24px; align-items:center;
  background:linear-gradient(135deg, var(--v), color-mix(in srgb, var(--v) 55%, #111827)); box-shadow:0 24px 50px -24px var(--v); }}
.hero .emoji {{ font-size:40px; line-height:1 }}
.hero h1 {{ margin:8px 0 6px; font-size:34px; letter-spacing:-.02em }}
.hero p {{ margin:0; font-size:17px; opacity:.95; max-width:600px }}
.hero .site {{ margin-top:12px; font-size:13px; opacity:.85; word-break:break-all }}
.ring {{ width:130px; height:130px; border-radius:50%; display:grid; place-items:center;
  background:conic-gradient(#fff 0 {pass_rate}%, rgba(255,255,255,.25) {pass_rate}% 100%); }}
.ring div {{ width:100px; height:100px; border-radius:50%; background:color-mix(in srgb, var(--v) 70%, #111827);
  display:grid; place-items:center; text-align:center; line-height:1.1 }}
.ring b {{ font-size:28px; display:block }} .ring span {{ font-size:11px; opacity:.85 }}
.nums {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-top:18px }}
.n {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:14px 16px; box-shadow:var(--shadow) }}
.n b {{ display:block; font-size:26px; letter-spacing:-.02em }} .n span {{ font-size:13px; color:var(--muted) }}
.n.ok b {{ color:var(--ok) }} .n.bad b {{ color:var(--bad) }}
.bar {{ display:flex; height:14px; border-radius:99px; overflow:hidden; background:var(--soft); margin-top:16px }}
.bar i {{ display:block; height:100% }}
.legend {{ display:flex; gap:16px; font-size:13px; color:var(--muted); margin-top:8px; flex-wrap:wrap }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; vertical-align:-1px }}
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:22px }}
.box {{ background:var(--card); border:1px solid var(--line); border-radius:18px; padding:18px 20px; box-shadow:var(--shadow) }}
.box h3 {{ margin-bottom:10px }}
.good {{ list-style:none; margin:0; padding:0 }} .good li {{ padding:6px 0 6px 30px; position:relative }}
.good li::before {{ content:"✓"; position:absolute; left:0; top:5px; width:20px; height:20px; border-radius:6px; background:var(--okbg);
  color:var(--ok); font-weight:800; font-size:12px; display:grid; place-items:center }}
.prio {{ display:flex; flex-direction:column; gap:8px }}
.prio div {{ display:flex; justify-content:space-between; padding:8px 12px; border-radius:10px; background:var(--soft) }}
.fix {{ display:grid; grid-template-columns:40px 1fr auto; gap:16px; background:var(--card); border:1px solid var(--line);
  border-left:5px solid var(--pc); border-radius:18px; padding:18px; margin-bottom:14px; box-shadow:var(--shadow) }}
.p-critical, .p-high {{ --pc:var(--bad); --pcbg:var(--badbg) }} .p-medium {{ --pc:var(--warn); --pcbg:var(--warnbg) }} .p-low {{ --pc:#94a3b8; --pcbg:var(--soft) }}
.num {{ width:34px; height:34px; border-radius:11px; background:var(--pcbg); color:var(--pc); font-weight:800; display:grid; place-items:center }}
.ftop {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap }}
.chip {{ font-size:11.5px; font-weight:800; padding:3px 10px; border-radius:99px; background:var(--pcbg); color:var(--pc) }}
.where {{ display:block; font-size:12.5px; margin:4px 0 8px; word-break:break-all; color:var(--muted) }}
.fix p {{ margin:6px 0 }} .why b {{ color:var(--fg) }} .how b {{ color:var(--ok) }}
.fshot {{ width:150px; border-radius:10px; border:1px solid var(--line) }}
.codefix {{ margin-top:10px }}
.clbl {{ font-size:12px; font-weight:700; display:flex; gap:8px; align-items:center }}
.clbl.now {{ color:var(--bad) }} .clbl.to {{ color:var(--ok) }} .clbl .muted {{ font-weight:500 }}
.codefix pre {{ margin:4px 0 10px; padding:10px 12px; border-radius:10px; font:12px/1.5 Consolas,monospace; white-space:pre-wrap; word-break:break-all }}
pre.now {{ background:var(--badbg); border-left:3px solid var(--bad) }} pre.to {{ background:var(--okbg); border-left:3px solid var(--ok) }}
.copy {{ margin-left:auto; border:1px solid var(--line); background:var(--card); color:var(--fg); border-radius:8px; padding:2px 10px; cursor:pointer; font-size:12px }}
.allgood {{ text-align:center; padding:40px; font-size:18px }}
.pages {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:14px }}
.page {{ background:var(--card); border:1px solid var(--line); border-radius:16px; overflow:hidden; box-shadow:var(--shadow) }}
.page.pbad {{ border-color:color-mix(in srgb, var(--bad) 40%, var(--line)) }}
.pshot {{ width:100%; height:140px; object-fit:cover; object-position:top; display:block; background:var(--soft) }}
.pshot.none {{ display:grid; place-items:center; color:var(--muted); font-size:12px }}
.pcap {{ padding:10px 12px; font-size:13px }} .pcap b {{ display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }}
.pcap .url {{ display:block; color:var(--muted); font-size:11.5px }}
.pstats {{ display:flex; gap:6px; flex-wrap:wrap; margin-top:6px }}
.pill {{ font-size:11.5px; font-weight:700; padding:2px 9px; border-radius:99px; background:var(--soft); color:var(--muted) }}
.pill.ok {{ background:var(--okbg); color:var(--ok) }} .pill.bad {{ background:var(--badbg); color:var(--bad) }} .pill.warn {{ background:var(--warnbg); color:var(--warn) }}
.fails {{ margin:6px 0 0; padding-left:18px; color:var(--bad); font-size:12px }}
.vpics {{ display:flex; gap:8px; flex-wrap:wrap }} .vpic {{ display:flex; flex-direction:column; align-items:center; font-size:11.5px }}
.vshot {{ width:150px; max-height:220px; object-fit:cover; object-position:top; border-radius:8px; border:1px solid var(--line) }}
details {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:12px 16px; margin-bottom:10px }}
summary {{ cursor:pointer; font-weight:700 }}
.tablewrap {{ overflow-x:auto; margin-top:10px }}
table {{ width:100%; border-collapse:collapse; font-size:13px }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top }}
th {{ font-size:11.5px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted) }}
td pre {{ white-space:pre-wrap; font-size:11.5px; color:var(--muted); margin:4px 0 0; max-height:160px; overflow:auto }}
@media (max-width:760px) {{ .hero {{ grid-template-columns:1fr }} .two {{ grid-template-columns:1fr }}
  .fix {{ grid-template-columns:34px 1fr }} .fshot {{ grid-column:2; width:100% }} .hero h1 {{ font-size:28px }} }}
</style></head><body><main>

<div class="brand"><span><b>Qpilot</b> · Website test report</span>
  <span>{datetime.now():%d %B %Y, %H:%M}</span></div>

<section class="hero">
  <div>
    <div class="emoji">{story['emoji']}</div>
    <h1>{_e(story['title'])}</h1>
    <p>{_e(story['text'])}</p>
    <div class="site">{_e(state.get('source') or state['url'])}{f" · started from {_e(proj['type'])} project" if proj else ""}</div>
  </div>
  <div class="ring" title="{_e(head['denominator'])}"><div><b>{pass_rate}%</b><span>of executed functional<br>cases passed<br>({head['passed']} of {head['of']})</span></div></div>
</section>
<div class="box" style="margin-top:16px;border-left:4px solid #7b72c5">
<h3>Exploration and functional test coverage</h3>
<p>{_e(clarity['coverage_limitations']['statement'])}</p>
<p>{_e(clarity['coverage_limitations']['limitation'])}</p>
<p>{clarity['pages_coverage']['visited']} page(s) visited of {clarity['pages_coverage']['discovered']} discovered;
  {clarity['pages_coverage']['not_visited']} not visited.
The percentage above covers {head['of']} executed functional test case(s), not every component or the whole website.
This report never claims the entire site was tested.</p>
</div>
<div class="nums">
  <div class="n ok"><b>{clarity['result_status_counts']['PASS']}</b><span>PASS</span></div>
  <div class="n bad"><b>{clarity['result_status_counts']['FAIL']}</b><span>FAIL (incl. flaky)</span></div>
  <div class="n"><b>{clarity['result_status_counts']['BLOCKED']}</b><span>BLOCKED</span></div>
  <div class="n"><b>{clarity['result_status_counts']['SKIPPED']}</b><span>SKIPPED</span></div>
  <div class="n"><b>{clarity['result_status_counts']['NOT TESTED']}</b><span>NOT TESTED</span></div>
  <div class="n"><b>{clarity['result_status_counts']['INCONCLUSIVE']}</b><span>INCONCLUSIVE</span></div>
</div>
<p class="muted">Test-case outcomes stay separate: blocked, skipped, not tested and inconclusive are never counted as PASS.</p>
{limits_html}

<div class="nums">
  <div class="n"><b>{len(app_map)}</b><span>pages checked</span></div>
  <div class="n"><b>{tcm['passed']} / {tcm['planned']}</b><span>test cases passed ({tcm['failed']} failed, {tcm['blocked']} blocked, {tcm['inconclusive'] + tcm['skipped']} inconclusive / skipped)</span></div>
  <div class="n"><b>{st['total']}</b><span>single tests ran ({st['groups']['links']['total']} of them link checks)</span></div>
  <div class="n {'bad' if fd['application_defects'] else 'ok'}"><b>{fd['application_defects']}</b><span>application defect(s) · {fd['test_problems']} test-script problem(s)</span></div>
  <div class="n {'bad' if fixes else 'ok'}"><b>{len(fixes)}</b><span>thing(s) to fix</span></div>
  <div class="n"><b>{_e(fmt_usd(cost['cost_usd'])) if used_ai else 'No AI'}</b><span>{f"AI cost · {_e(fmt_usd(cost['avg_cost_per_case_usd']))} per test case" if used_ai else 'built-in rules, $0'}</span></div>
</div>
<div class="bar"><i style="width:{pct(passed)};background:var(--ok)"></i><i style="width:{pct(failed)};background:var(--bad)"></i><i style="width:{pct(skipped)};background:#94a3b8"></i></div>
<div class="legend"><span>All {st['total']} single tests:</span><span><i style="background:var(--ok)"></i>{passed} passed</span><span><i style="background:var(--bad)"></i>{failed} failed</span>
  <span><i style="background:#94a3b8"></i>{skipped} skipped (reason shown per test)</span>
  {f'<span>❔ {unclear} inconclusive (ran, but could not establish the result - not counted as passed)</span>' if unclear else ''}
  <span>{'✓ all totals add up' if m['consistent'] else '✗ some totals do NOT add up - see the consistency checks'}</span></div>
{'' if m['consistent'] else '<div class="box" style="margin-top:12px;border-left:4px solid #b45309"><h3>Metrics consistency FAILED</h3><p>Report totals do not add up. Treat PASS rates and “no bugs” claims as unreliable until the consistency checks below are green.</p><ul>' + ''.join(f"<li><b>{_e(c['check'])}</b> — {_e(c['detail'])}</li>" for c in m['consistency'] if not c['ok']) + '</ul></div>'}

<div class="two">
  <div class="box"><h3>✅ What works well</h3>
    {f'<ul class="good">{"".join(f"<li>{_e(g)}</li>" for g in good)}</ul>' if good else '<p class="muted">Nothing could be confirmed yet.</p>'}</div>
  <div class="box"><h3>🔧 What needs fixing</h3>
    {f'''<div class="prio">
      <div><span>🔴 Fix first</span><b>{by_prio["critical"] + by_prio["high"]}</b></div>
      <div><span>🟠 Should fix</span><b>{by_prio["medium"]}</b></div>
      <div><span>⚪ Nice to fix</span><b>{by_prio["low"]}</b></div></div>
      <p class="muted">Each one is explained below: why it matters, and exactly what to change.</p>''' if fixes else (
        '<p>Insufficient Evidence — findings are provisional, untriaged, or the run did not finish; not “zero bugs”.</p>'
        if (state.get("incomplete") or any(f.get("provisional") for f in failures) or not m["consistent"])
        else '<p>No triaged problems confirmed in this run (not a whole-product “zero bugs” claim).</p>')}</div>
</div>

{gates_html}

{numbers_html}

<h2>What to fix, step by step</h2>
{fix_cards or (
    '<div class="box">Insufficient Evidence — do not treat an empty fix list as “zero bugs” while the run is incomplete, '
    'findings are provisional, or consistency checks failed.</div>'
    if (state.get("incomplete") or any(f.get("provisional") for f in failures) or not m["consistent"])
    else '<div class="box allgood">No triaged fixes from this run. That is not a claim that every page or workflow is bug-free.</div>')}

{confidence_html}

{coverage3_html}

{compare_html}

{visual_html(vis)}

<h2>Page by page</h2>
<div class="pages">{page_cards}</div>

{coverage_html}

<h2>Technical details</h2>
<details><summary>Frontend changes since the last test</summary>{changes_html}</details>
<details><summary>Self-healing: {len(heals)} script repair(s) tried - {sum(1 for h in heals if h['status'] == 'healed')} pass now,
  {sum(1 for h in heals if h['status'] == 'repaired')} work and fail on a real check,
  {sum(1 for h in heals if h['status'] in ('reverted', 'still failing', 'could not heal'))} not repaired (every repair was run again before it was kept)</summary>
  {_table(["Result", "Script", "Repair"], heal_rows, "No test scripts needed repairing.")}</details>
<details><summary>AI cost of this run</summary>{cost_html}</details>
<details><summary>Bug reports - suspected website bugs ({len(bugs)})</summary>{bug_html or '<p class="muted">No suspected website bugs.</p>'}</details>
<details><summary>All findings ({len(failures)})</summary>{_table(["Severity", "Type", "Page", "What went wrong"], finding_rows, "No findings.")}</details>
<details><summary>All test results ({len(results)})</summary>{_table(["", "Script", "Test", "Result", "Checks", "Time", "Evidence"], result_rows, "No tests ran.")}</details>
<details><summary>Agent log</summary><ol>{log_items}</ol></details>

</main>
<script>
function copyCode(b) {{
  const pre = b.parentElement.nextElementSibling;
  navigator.clipboard.writeText(pre.innerText).then(() => {{ b.textContent = 'Copied'; setTimeout(() => b.textContent = 'Copy', 1500); }},
    () => {{ b.textContent = 'Select + Ctrl+C'; }});
}}
</script>
</body></html>"""

    from ..page_inventory import save_inventory
    save_inventory(run_dir, app_map, reg)
    component_link = '<section class="box"><h2>Page component inventory</h2><p><a href="components.html">Browse components by page and observed state</a> | <a href="components.json">Download inventory JSON</a></p><p>Discovery and functional verification are separate. Hidden, opaque and limited areas are identified.</p></section>'
    doc = doc.replace("</body>", component_link + "</body>")
    report = run_dir / "report.html"
    report.write_text(doc, encoding="utf-8")
    login = state.get("login") or {}
    authenticated_pages = sum(1 for p in app_map if p.get("auth"))
    (run_dir / "summary.json").write_text(json.dumps({
        "exploration": (state.get("crawl") or {}).get("exploration"),
        "url": state["url"], "verdict": verdict, "reasons": reasons, "gates": gates, "pages": len(app_map),
        "authenticated": bool(login.get("logged_in")), "authenticated_pages": authenticated_pages,
        "login_note": login.get("note", ""), "login_outcome": login.get("outcome", "not_required"),
        "login_evidence": login.get("evidence", []), "coverage": cov3,
        "comparison": {k: comparison.get(k) for k in ("previous_run", "previous_verdict", "counts")},
        "visual": (vis or {}).get("counts"),  # pages the same / changed / new vs. the approved look
        "finished": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tests": len(results), "passed": passed, "failed": failed, "skipped": skipped, "inconclusive": unclear,
        "flaky": sum(bool(r.get("flaky")) for r in results), "findings": len(failures),
        "bugs": len(bugs),
        "test_cases": len(cases), "scripts": len(state.get("scripts", [])),
        "healed": sum(1 for h in heals if h["status"] == "healed"),
        "repaired_real_failure": sum(1 for h in heals if h["status"] == "repaired"), "fixes": len(fixes),
        "source": state.get("source"), "run_id": state["run_id"],
        "cost_usd": cost["cost_usd"], "cost_per_case_usd": cost["avg_cost_per_case_usd"],
        "tokens": cost["tokens_in"] + cost["tokens_out"], "llm": f"{cost['provider']} {cost['model']}".strip(),
        "run_seconds": cost["run_seconds"],
        "incomplete": bool(state.get("incomplete")), "incomplete_reason": state.get("incomplete_reason", ""),
        "stopped_at": state.get("stopped_at", ""), "limits_hit": limits,
        "environment": cfg.environment, "writes": cfg.writes_note, "coverage_card": card, "seen_by_ai": seen_summary,
        "coverage_confidence": confidence,
        "result_status_counts": clarity["result_status_counts"],
        "feature_status_counts": clarity["feature_status_counts"],
        "pages_coverage": clarity["pages_coverage"],
        "pages_discovered": clarity["pages_coverage"]["discovered"],
        "pages_visited": clarity["pages_coverage"]["visited"],
        "pages_not_visited": clarity["pages_coverage"]["not_visited"],
        "coverage_limitations": clarity["coverage_limitations"],
        "data_created": {k: created[k] for k in ("created", "deleted")} | {"left": len(created["left"])},
        # plain-English story for the web page; pass_rate = the share of FUNCTIONAL test cases that passed (its
        # denominator: metrics.headline) - every number above comes from metrics (metrics.json); never overall accuracy %
        "headline": story, "working_well": good, "pass_rate": pass_rate,
        "metrics": {k: m[k] for k in ("single_tests", "assertions", "test_cases", "workflows", "findings", "rates",
                                      "headline", "consistency", "consistent", "result_status_counts",
                                      "feature_status_counts")}}, indent=2), encoding="utf-8")
    log = state.get("log", []) + [f"Report: verdict = {verdict}."]
    return {"verdict": verdict, "report_path": str(report), "log": log}
