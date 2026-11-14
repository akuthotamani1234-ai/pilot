"""Mobile report adapters using the existing deterministic release-verdict engine."""

import html
import json
import re
from pathlib import Path

from .android_design import normalize_case
from .safety import redact, redact_json


def classify_failure(result: dict) -> str:
    kind = result.get("exception_type", "")
    # Classify the exception, not source-code words embedded in a pytest traceback.
    if kind in ("AppCrash", "AppNotResponding"):
        return "app_crash"
    if kind in ("AssertionError",):
        return "assertion_failure"
    if kind in ("NoSuchElementException", "StaleElementReferenceException", "InvalidSelectorException"):
        return "locator"
    if result["outcome"] == "inconclusive":
        return "inconclusive"
    if kind in (
        "AndroidEnvironmentError",
        "SessionNotCreatedException",
        "InvalidSessionIdException",
        "WebDriverException",
        "ConnectionError",
        "ReadTimeoutError",
        "TimeoutException",
        "RuntimeError",
        "ValueError",
        "TimeoutError",
    ):
        return "infrastructure"
    message = result.get("error", "").splitlines()[0] if result.get("error") else ""
    if "AssertionError" in message:
        return "assertion_failure"
    if any(term in message for term in ("NoSuchElement", "StaleElement", "InvalidSelector")):
        return "locator"
    return "infrastructure" if result["outcome"] == "error" or kind else "assertion_failure"


def analyze(state: dict) -> dict:
    cases = {c["id"]: c for c in state.get("test_cases", [])}
    failures = []
    for result in state.get("results", []):
        if result["outcome"] in ("passed", "blocked"):
            continue
        case = cases.get(result["id"], {})
        category = classify_failure(result)
        failures.append(
            {
                "id": result["id"],
                "title": result.get("title", case.get("title", result["id"])),
                "category": category,
                "source": "test",
                "severity": "high" if category in ("assertion_failure", "app_crash") else "medium",
                "confidence": "high"
                if category == "app_crash" or category == "assertion_failure" and case.get("expected_screen_name")
                else "medium",
                "tc_id": case.get("tc_id"),
                "explanation": redact(result.get("error", ""))[:1000],
                "screenshot": result.get("screenshot"),
                "video": result.get("video"),
                "logcat": result.get("logcat"),
                "evidence": "Actual pytest/Appium result" + (" + device log" if result.get("logcat") else "")
                + (" + screen recording" if result.get("video") else ""),
                "recommended_fix": "Open the saved device log: its stack trace shows where the app crashed."
                if category == "app_crash"
                else "Compare the app behavior with the supplied expected result."
                if category == "assertion_failure"
                else "Check device connectivity and the foreground screen; inspect the original locator evidence.",
            }
        )
    (Path(state["run_dir"]) / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    return {"failures": failures}


def mobile_quality_gates(state: dict) -> list[dict]:
    from .agents.reporter import _gate
    from .android_features import feature_matrix

    results = state.get("results", [])
    cases = state.get("test_cases", [])
    setup = state.get("setup_error")
    if not state.get("screens"):
        return [_gate("app_started", "The Android app launches", "missing", setup or "No app screen was inspected.")]
    screens = state.get("screens", [])
    def has_login_form(screen):
        password = any(e.get("visible") and e.get("input_capable") and e.get("password")
                       for e in screen.get("elements", []))
        submit = any(e.get("visible") and e.get("clickable")
                     and re.search(r"\b(log ?in|sign ?in)\b",
                                   " ".join((e.get("text") or "", e.get("accessibility_id") or "")), re.I)
                     for e in screen.get("elements", []))
        return password and submit

    def password_box(element):
        words = " ".join(str(element.get(k) or "") for k in ("resource_id", "accessibility_id", "hint")).casefold()
        return element.get("input_capable") and element.get("visible", True) and (element.get("password")
                                                                                  or "password" in words)

    login_screens = [screen for screen in screens if has_login_form(screen)]
    # A password box on the very first screen is an authentication wall even when its submit button was not read.
    launch_auth_wall = bool(screens and (has_login_form(screens[0])
                                         or any(password_box(e) for e in screens[0].get("elements", []))))
    if launch_auth_wall and screens[0] not in login_screens:
        login_screens.append(screens[0])
    auth_verified = any(r.get("authentication_verified") and r.get("outcome") == "passed" for r in results)
    auth_missing = bool(login_screens) and not auth_verified
    answered = [
        r
        for r in results
        if r["outcome"] == "passed" or r["outcome"] == "failed" and classify_failure(r) == "assertion_failure"
    ]
    by_id = {case["id"]: case for case in cases}
    changed_labels = [
        r
        for r in results
        if r["outcome"] == "failed"
        and classify_failure(r) == "assertion_failure"
        and by_id.get(r["id"], {}).get("requirement") == "Observed UI regression evidence"
    ]
    bad = [
        r
        for r in results
        if r["outcome"] == "failed" and classify_failure(r) == "assertion_failure" and r not in changed_labels
    ]
    unknown = [
        r
        for r in results
        if r["outcome"] in ("error", "inconclusive")
        or r["outcome"] == "failed"
        and classify_failure(r) in ("infrastructure", "locator")
    ]
    blocked = sum(c.get("blocked_count", 1) for c in cases if c.get("blocked"))
    inferred = sum(c.get("functionality_status") == "inferred" for c in cases)
    missing_functional = feature_matrix(state)['controls_needing_functional_checks_count']
    return [
        _gate('functional_scope', 'Observed functionality has explicit checks', 'risk' if missing_functional else 'pass',
              f'{missing_functional} observed interactive controls have no passing configured functionality check. Visibility checks do not verify business behavior.', mandatory=False),
        _gate("ai_provider", "Selected AI availability", "risk" if state.get("ai_warnings") else "pass",
              " ".join(state.get("ai_warnings", [])) or "No AI fallback was recorded.", mandatory=False),
        _gate("app_started", "The Android app launches", "pass", "Actual app hierarchy was inspected."),
        _gate(
            "tests_ran",
            "Meaningful Android tests ran",
            "pass" if answered else "missing",
            f"{len(answered)} answered test(s).",
        ),
        _gate(
            "mobile_assertions",
            "Expected Android behavior passed",
            "fail" if bad else "pass",
            f"{len(bad)} failed assertion(s).",
        ),
        _gate(
            "automation",
            "Android execution was conclusive",
            "missing" if unknown else "pass",
            f"{len(unknown)} infrastructure, locator or inconclusive result(s).",
        ),
        _gate(
            "coverage",
            "Coverage and unresolved requirements",
            "risk"
            if blocked
            or inferred
            or state.get("discovery_issues")
            or state.get("unvisited")
            or state.get("cases_left_out")
            or any(r.get("platform_recoveries") for r in results)
            else "pass",
            f"{blocked} blocked controls; {inferred} inferred scenarios; {len(state.get('unvisited', []))} unexplored controls; "
            f"{state.get('cases_left_out', 0)} omitted cases. Discovery is bounded, not proof of complete app coverage.",
            mandatory=False,
        ),
        _gate(
            "authentication",
            "Protected functionality was reachable",
            "missing" if auth_missing else "pass",
            "The approved login flow passed; authenticated screens were available for exploration."
            if auth_verified else
            "The app starts at a login screen. Approved credentials and post-login evidence are needed to reach protected screens."
            if launch_auth_wall else
            "A login form was found behind navigation, but no approved account was supplied; protected screens were not explored."
            if login_screens else
            "No password-based login form was discovered; no login was attempted.",
        ),
        _gate(
            "observed_changes",
            "Observed UI changes reviewed",
            "risk" if changed_labels else "pass",
            f"{len(changed_labels)} observed-label change(s) need review; these are not confirmed business-rule defects.",
            mandatory=False,
        ),
        _gate(
            "healing",
            "Automatic locator recovery reviewed",
            "risk" if state.get("healing_log") else "pass",
            f"{len(state.get('healing_log', []))} locator recovery attempt(s).",
            mandatory=False,
        ),
    ]


AREA_NAMES = {"menu": "Menu", "footer": "Footer", "page": "Page", "form": "Form", "cart": "Cart", "select": "Drop-down",
              "control": "Control", "login": "Login", "journey": "AI journey", "phone": "Phone", "feature": "Feature"}


def user_coverage(interaction: dict, cases: list[dict], results: list[dict]) -> dict:
    """The coverage list of test mode, with each kept check's result from the final run (passed / failed with the
    reason and screenshot / not tested with the reason). Every number is counted from these rows."""
    by_flow = {c.get("auto_flow_id"): c for c in cases if c.get("auto_flow_id")}
    by_id = {r.get("id"): r for r in results}
    ran = bool(results)
    rows = []
    for row in interaction.get("coverage") or []:
        row = dict(row)
        flow = row.get("flow_id")
        if flow:
            case = by_flow.get(flow)
            result = by_id.get(case["id"]) if case else None
            if case is None:
                row.update(status="not tested", reason="kept during exploration, but left out by the limit of test cases "
                                                       "for this run")
            elif result is None:
                row["reason"] = (row.get("reason") or "") + (" (the final run did not reach this test)" if ran
                                                             else " (exploration result; the final run did not happen)")
                if ran:
                    row["status"] = "not tested"
            elif result.get("outcome") == "passed":
                row.update(status="passed", reason="passed in the final run; " + (row.get("reason") or ""))
            elif result.get("outcome") in ("failed", "error"):
                first = (result.get("error") or "").strip().splitlines()
                row.update(status="failed", reason=(first[0] if first else "failed in the final run")[:300],
                           screenshot=result.get("screenshot") or row.get("screenshot"))
            else:
                row.update(status="not tested", reason=(result.get("error") or "not run in the final run")[:300])
        rows.append(row)
    counts = {status: sum(r.get("status") == status for r in rows) for status in ("passed", "failed", "not tested")}
    areas = {}
    for row in rows:
        area = areas.setdefault(row.get("area", "feature"), {"passed": 0, "failed": 0, "not tested": 0})
        area[row.get("status", "not tested")] = area.get(row.get("status", "not tested"), 0) + 1
    return {"rows": rows, "counts": counts, "areas": areas, "mode": interaction.get("mode", "")}


def control_coverage(state: dict, features: dict, cases: list[dict], results: list[dict]) -> dict:
    """Every discovered button, link and input box, each with tested - passed / tested - failed / not tested and the
    plain reason (a never-pressed rule, a device feature, the candidate cap, the time limit, not reached...)."""
    by_id = {r.get("id"): r for r in results}
    titles = {c["id"]: c.get("title", c["id"]) for c in cases}
    element_cases = {}
    for case in cases:
        for element_id in case.get("element_ids", []):
            element_cases.setdefault(element_id, []).append(case["id"])
    unvisited = {u.get("element_id"): u.get("reason") for u in state.get("unvisited", []) if u.get("element_id")}
    interaction = state.get("interaction") or {}
    why = {}
    for item in [*interaction.get("tried", []), *interaction.get("coverage", [])]:
        match = re.match(r"(?:Tap )?'(.+?)'", str(item.get("check") or item.get("name") or ""))
        reason = item.get("reason") or ""
        if match and reason and item.get("outcome") != "kept" and item.get("status") != "passed":
            why.setdefault(match.group(1).casefold(), reason)
    test_mode = bool(interaction.get("enabled"))
    rows = []
    for component in features.get("components", []):
        if not component.get("interactive"):
            continue
        linked = sorted(set(component.get("configured_checks", [])) | set(element_cases.get(component["element_id"], [])))
        outcomes = {cid: (by_id.get(cid) or {}).get("outcome") for cid in linked}
        failed = [cid for cid, outcome in outcomes.items() if outcome in ("failed", "error")]
        row = {"screen": component["screen"], "name": component.get("name") or "control", "type": component.get("type"),
               "element_id": component["element_id"]}
        if component.get("passing_configured_checks"):
            row.update(status="passed", reason="used in a passing test: " + titles.get(
                component["passing_configured_checks"][0], component["passing_configured_checks"][0]))
        elif failed:
            result = by_id[failed[0]]
            first = (result.get("error") or "failed").strip().splitlines()
            row.update(status="failed", reason=f"{titles.get(failed[0], failed[0])}: {first[0][:200] if first else ''}",
                       screenshot=result.get("screenshot"))
        elif component.get("visibility_checked"):
            row.update(status="not tested", presence_checked=True,
                       reason="Its presence was checked, but the control was not exercised in a passing functional test.")
        else:
            reason = (unvisited.get(component["element_id"]) or why.get(str(row["name"]).casefold())
                      or ("not reached by the checks of this run" if test_mode else
                          "not used: safe discovery only opens screens; tick test mode to use it"))
            row.update(status="not tested", reason=reason)
        rows.append(row)
    counts = {status: sum(r["status"] == status for r in rows) for status in ("passed", "failed", "not tested")}
    return {"rows": rows, "counts": counts}


def early_stop(state: dict) -> str:
    """Why exploration or user-like testing stopped before the end (time, Stop, recovering, the app left), in plain
    words with the number of controls not reached; '' when it did not."""
    reasons = []
    recovery = next((i for i in state.get("discovery_issues", []) if i.get("recovery_heavy")), None)
    if recovery:
        reasons.append(recovery["error"])
    stopped = (state.get("interaction") or {}).get("stopped")
    if stopped:
        unreached = sum(r.get("status") == "not tested" and any(w in r.get("reason", "") for w in
                                                               ("limit", "stopped", "not reached", "time"))
                        for r in (state.get("interaction") or {}).get("coverage", []))
        reasons.append(f"User-like testing stopped early ({stopped}); {unreached} planned checks were not reached.")
    elif any("limit reached" in str(i.get("error", "")) for i in state.get("discovery_issues", [])) and state.get("unvisited"):
        reasons.append(f"Exploration stopped at its limit; {len(state['unvisited'])} controls were not reached.")
    return " ".join(reasons)


def report(state: dict) -> dict:
    from .agents.reporter import decide_verdict
    from .cost import write_report
    from .excel import automation_status, case_result, write_workbook

    run_dir = Path(state["run_dir"])
    cases = [normalize_case(c) for c in state.get("test_cases", [])]
    results = state.get("results", [])
    # Backward compatibility for earlier Android runs and their downloaded case files.
    for result in results:
        result.setdefault("file", "test_android_generated.py")
        result.setdefault("test", "test_" + result["id"])
    state = {**state, "test_cases": cases, "target_type": "mobile"}
    verdict, reasons, gates = decide_verdict(state)
    for case in cases:
        case["execution_status"], case["actual_result"] = case_result(case, results)
        case["automation_status"], case["automated_by"] = automation_status(case, run_dir / "generated_tests")
        case["evidence"] = [r["screenshot"] for r in results if r.get("screenshot") and r["id"] == case["id"]]
    completed = {r.get("id") for r in results if r.get("outcome") == "passed"}
    planned = {eid for c in cases if not c.get("blocked") for eid in c.get("element_ids", [])}
    referenced = {eid for c in cases if c["id"] in completed and not c.get("blocked") for eid in c.get("element_ids", [])}
    coverage_pages = [
        {
            "url": screen.get("web_url") or "android://" + screen["package_name"] + "/" + screen["id"],
            "items": [
                {
                    "selector": e["id"],
                    "name": e.get("accessibility_id") or e.get("text") or e.get("resource_id") or "element",
                    "kind": e["type"],
                    "status": "tested" if e["id"] in referenced else "not tested",
                    "reason": "Checked in a completed passing mobile case"
                    if e["id"] in referenced
                    else "Planned; no completed passing execution evidence" if e["id"] in planned
                    else "No approved executable scenario",
                }
                for e in screen["elements"]
            ],
        }
        for screen in state.get("screens", [])
    ]
    coverage = {
        "pages": coverage_pages,
        "tested": len(referenced),
        "planned": len(planned),
        "total": sum(len(p["items"]) for p in coverage_pages),
        "screens": len(state.get("screens", [])),
        "unvisited": state.get("unvisited", []),
    }
    config = state.get("config", {})
    from .android_features import feature_matrix

    features = feature_matrix(state)
    coverage_reasons = []
    if features['controls_needing_functional_checks_count']:
        coverage_reasons.append(f"{features['controls_needing_functional_checks_count']} discovered interactive controls "
                                "still need passing functional checks")
    if state.get("discovery_issues"):
        coverage_reasons.append("screen discovery reported an issue")
    if state.get("unvisited"):
        coverage_reasons.append(f"{len(state['unvisited'])} discovered items remain unvisited")
    if state.get("cases_left_out"):
        coverage_reasons.append(f"{state['cases_left_out']} planned cases were omitted")
    interaction_stop = (state.get("interaction") or {}).get("stopped")
    if interaction_stop:
        coverage_reasons.append("user-like testing stopped: " + str(interaction_stop))
    bot_check = state.get("bot_check") or {}
    if bot_check.get("blocked"):
        # The first thing the report says: nothing behind the website's bot check was tested.
        coverage_reasons.insert(0, str(bot_check.get("message") or "the website's bot check stopped the run"))
    if state.get("incomplete_reason"):
        coverage_reasons.append(state["incomplete_reason"])
    incomplete = bool(state.get("incomplete") or state.get("setup_error") or coverage_reasons)
    incomplete_reason = state.get("incomplete_reason") or state.get("setup_error", "")
    if bot_check.get("blocked") and bot_check.get("message") and bot_check["message"] not in incomplete_reason:
        incomplete_reason = (str(bot_check["message"]) + " " + incomplete_reason).strip()
    if not incomplete_reason and coverage_reasons:
        incomplete_reason = "Whole-app coverage is incomplete: " + "; ".join(coverage_reasons) + "."
    counts = {
        outcome: sum(r["outcome"] == outcome for r in results)
        for outcome in ("passed", "failed", "error", "blocked", "inconclusive", "skipped")
    }
    screens = state.get("screens", [])
    summary = {
        "source": state.get("source", "Android application"),
        "url": config.get("start_url") or state.get("source", "Android application"),
        "automation_mode": "android_chrome" if config.get("app_mode") == "web" else "native",
        "target_type": "android",
        "platform": "android",
        "run_id": state["run_id"],
        "verdict": verdict,
        "reasons": reasons,
        "gates": gates,
        "incomplete": incomplete,
        "incomplete_reason": incomplete_reason,
        "package_name": screens[0].get("package_name") if screens else config.get("package_name"),
        "device_id": config.get("device_id"),
        "android_version": screens[0].get("android_version") if screens else None,
        "driver": "UiAutomator2",
        "application_version": config.get("app_version"),
        "driver_information": state.get("environment", {}).get("driver_output"),
        "pages": len(screens),
        "screens_visited": len(screens),
        "tests": len(results),
        "test_cases": len(cases),
        "scripts": len(state.get("scripts", [])),
        "script_sources": state.get("script_sources", {}),
        "ai_warnings": state.get("ai_warnings", []),
        "contract_tests": sum(bool(r.get("contract_id")) for r in results),
        "contract_evidence": [e for r in results for e in r.get("contract_evidence", [])],
        "platform_recoveries": [event for issue in state.get("discovery_issues", [])
                                for event in issue.get("platform_recoveries", [])]
        + max((r.get("platform_recoveries", []) for r in results), key=len, default=[]),
        "self_healing_attempts": len(state.get("healing_log", [])),
        "counts": counts,
        **counts,
        "duration_s": state.get("execution_duration_s"),
        "coverage": coverage,
        'functional_checks': features['functional_checks'],
        'ui_checks': features['ui_checks'],
        'controls_needing_functional_checks': features['controls_needing_functional_checks'],
        'controls_needing_functional_checks_count': features['controls_needing_functional_checks_count'],
        "controls": control_coverage(state, features, cases, results),
        "early_stop": early_stop(state),
        "thorough": bool(config.get("thorough")),
        "interaction": {**(state.get("interaction") or {}), "kept": len(state.get("auto_flows", []))},
        "bot_check": bot_check,
        "user_like_coverage": user_coverage(state.get("interaction") or {}, cases, results),
        "user_like_tests": {
            "total": sum(bool(c.get("auto_flow_id")) for c in cases),
            "passed": sum(r["outcome"] == "passed" for r in results if r.get("auto_flow_id")),
            "failed": sum(r["outcome"] in ("failed", "error") for r in results if r.get("auto_flow_id")),
        },
        "app_crashes": sum(r.get("exception_type") in ("AppCrash", "AppNotResponding") for r in results),
    }
    for name, value in (
        ("summary.json", summary),
        ("test_cases.json", cases),
        ("results.json", results),
        ("failures.json", state.get("failures", [])),
        ("app_map.json", state.get("app_map", [])),
        ("healing_log.json", state.get("healing_log", [])),
        ("coverage.json", {**summary["coverage"], "controls": summary["controls"]["rows"],
                           "user_like": summary["user_like_coverage"]["rows"]}),
        ('features.json', features),
    ):
        (run_dir / name).write_text(redact_json(value), encoding="utf-8")
    cost = write_report(run_dir, cases, results)
    write_workbook(run_dir, cases, results, cost=cost)
    content = render_mobile_report(
        summary, cases, results, state.get("failures", []), screens, state.get("healing_log", [])
    )
    path = run_dir / "report.html"
    path.write_text(redact(content), encoding="utf-8")
    return {
        "verdict": verdict,
        "report_path": str(path),
        "test_cases": cases,
        "log": state.get("log", []) + ["Android report written: " + verdict],
    }


def collect_healing(state: dict) -> dict:
    from .android_pipeline import read_jsonl

    entries = read_jsonl(Path(state["run_dir"]) / "android_healing.jsonl")
    (Path(state["run_dir"]) / "healing_log.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return {"healing_log": entries}


def render_mobile_report(summary, cases, results, failures, screens, healing):
    """Evidence-first presentation: real counts, bounded scope and links to captured artifacts."""
    from .agents.reporter import COLORS

    esc = lambda value: html.escape(str(value or ""), quote=True)  # noqa: E731
    counts = summary["counts"]
    color = COLORS.get(summary["verdict"], "#64748b")
    cards = "".join(
        f'<div class="metric"><b>{value}</b><span>{esc(label)}</span></div>'
        for label, value in (
            ("Screens inspected", summary["screens_visited"]),
            ("Tests passed", counts["passed"]),
            ("Assertions failed", counts["failed"]),
            ("Execution errors", counts["error"]),
            ("Blocked controls", sum(c.get("blocked_count", 1) for c in cases if c.get("blocked"))),
            ("Locator recovery attempts", summary["self_healing_attempts"]),
        )
        + ((("User-like tests passed", summary["user_like_tests"]["passed"]),
            ("App crashes / ANRs", summary["app_crashes"])) if summary.get("user_like_tests", {}).get("total") else ())
    )
    rows = "".join(
        "<tr><td><b>"
        + esc(case["title"])
        + "</b><small>"
        + esc(case["tc_id"])
        + '</small></td><td><span class="badge">'
        + esc(case["execution_status"])
        + "</span></td><td>"
        + esc(case["expected"])
        + "</td><td>"
        + esc(case["generation_source"])
        + " / "
        + esc(case.get("script_source", "none"))
        + "</td></tr>"
        for case in cases
    )
    gates = "".join(
        "<tr><td>"
        + esc(gate["name"])
        + "</td><td>"
        + esc(gate["status"].upper())
        + "</td><td>"
        + esc(gate["detail"])
        + "</td></tr>"
        for gate in summary["gates"]
    )
    def evidence_links(record):
        links = []
        for key, text, folder, suffix in (("video", "Screen recording", "videos/", ".mp4"),
                                          ("logcat", "Device log", "logcat/", ".txt")):
            path = record.get(key) or ""
            if path.startswith(folder) and path.endswith(suffix) and ".." not in path.split("/"):
                links.append('<a href="' + esc(path) + '">' + text + "</a>")
        return ('<p class="actions">' + "".join(links) + "</p>") if links else ""

    findings = "".join(
        '<article class="finding"><b>'
        + esc(failure.get("title") or "")
        + " - "
        + esc(failure["category"].replace("_", " "))
        + "</b><pre>"
        + esc(failure.get("explanation"))
        + "</pre><p>"
        + esc(failure.get("recommended_fix"))
        + "</p>"
        + evidence_links(failure)
        + "</article>"
        for failure in failures
    )
    interaction = summary.get("interaction") or {}
    tried_rows = "".join(
        "<tr><td>" + esc(item.get("check")) + "</td><td>" + esc(item.get("outcome")) + "</td><td>"
        # the specific reason (why a control is never pressed) before the generic detail
        + esc(" - ".join(x for x in (item.get("reason"), item.get("detail")) if x)) + "</td></tr>"
        for item in interaction.get("tried", [])[:200]
    )
    covered = summary.get("user_like_coverage") or {}
    labels = {"passed": "Tested - passed", "failed": "Tested - failed", "not tested": "Not tested"}

    def shot(path):
        path = str(path or "")
        if path.startswith("screenshots/") and path.endswith(".png") and ".." not in path.split("/"):
            return '<a href="' + esc(path) + '">Screenshot</a>'
        return ""
    coverage_rows = "".join(
        "<tr><td>" + esc(AREA_NAMES.get(row.get("area"), row.get("area"))) + "</td><td>" + esc(row.get("name"))
        + "</td><td>" + esc(row.get("where")) + "</td><td><span class=\"badge\">"
        + esc(labels.get(row.get("status"), row.get("status"))) + "</span></td><td>" + esc(row.get("reason"))
        + (" (" + esc(row.get("how_to_reach")) + ")" if row.get("how_to_reach") else "") + "</td><td>"
        + shot(row.get("screenshot")) + "</td></tr>"
        for row in covered.get("rows", [])[:1500]
    )
    counts_line = covered.get("counts") or {}
    coverage_section = (
        '<section id="what-was-tested"><h2>What was tested</h2><p>Every menu entry, page and feature test mode found, '
        f'with its result: <b>{esc(counts_line.get("passed", 0))}</b> tested and passed, '
        f'<b>{esc(counts_line.get("failed", 0))}</b> tested and failed, '
        f'<b>{esc(counts_line.get("not tested", 0))}</b> not tested (each with the reason).</p>'
        '<div class="table"><table><tr><th>Area</th><th>What</th><th>Where</th><th>Result</th><th>Reason</th>'
        '<th>Evidence</th></tr>' + coverage_rows + '</table></div></section>') if covered.get("rows") else ""
    labels_control = {"passed": "Tested - passed", "failed": "Tested - failed", "not tested": "Not tested"}
    control_rows = "".join(
        "<tr><td>" + esc(row.get("screen")) + "</td><td>" + esc(row.get("name")) + "</td><td>" + esc(row.get("type"))
        + '</td><td><span class="badge">' + esc(labels_control.get(row.get("status"), row.get("status")))
        + "</span></td><td>" + esc(row.get("reason")) + "</td><td>" + shot(row.get("screenshot")) + "</td></tr>"
        for row in (summary.get("controls") or {}).get("rows", [])[:1500])
    control_counts = (summary.get("controls") or {}).get("counts") or {}
    controls_section = (
        '<section id="every-control"><h2>Every control</h2><p>Each discovered button, link and input box: '
        f'<b>{esc(control_counts.get("passed", 0))}</b> tested and passed, <b>{esc(control_counts.get("failed", 0))}</b> '
        f'tested and failed, <b>{esc(control_counts.get("not tested", 0))}</b> not tested (with the reason).</p>'
        '<div class="table"><table><tr><th>Screen</th><th>Control</th><th>Type</th><th>Result</th><th>Reason</th>'
        '<th>Evidence</th></tr>' + control_rows + "</table></div></section>") if control_rows else ""
    early = ('<section class="scope stop"><b>Stopped early</b><p>' + esc(summary.get("early_stop")) + "</p></section>"
             if summary.get("early_stop") else "")
    bot = summary.get("bot_check") or {}
    if bot.get("blocked"):
        bot_section = ('<section class="scope stop"><b>Stopped at the website\'s bot check</b><p>'
                       + esc(bot.get("message")) + "</p><p>Qpilot never solves, hides from or tricks a bot check. "
                       "No test was made from the check page.</p></section>")
    elif bot.get("events"):
        bot_section = ('<section class="scope"><b>The website showed a bot check</b><p>'
                       + esc("; ".join(f"{e.get('kind')}: {e.get('outcome')} after {e.get('waited_s')} s"
                                       for e in bot["events"][:5])) + "</p></section>")
    else:
        bot_section = ""
    interaction_findings = "".join(
        "<li><b>" + esc(item.get("finding")) + "</b> on " + esc(item.get("screen")) + ": " + esc(item.get("detail")) + "</li>"
        for item in interaction.get("findings", [])
    )
    if interaction.get("enabled"):
        website = interaction.get("mode") == "website"
        interaction_section = (
            '<section id="user-like"><h2>User-like testing (' + ("test website" if website else "test build") + ')</h2><p>'
            + ("Every menu, every page to its end and every feature were used like a manual tester. Kept tests were "
               "replayed from a fresh visit (this website's cookies and storage cleared) before they were kept. "
               if website else
               "Discovered controls, forms and phone checks were tried like a manual tester. Kept tests were replayed "
               "from cleared app data before they were kept. ")
            + "Checkout, payment, placing an order, paid plans, deleting an account, crash buttons, sharing, calls and "
            "SMS are never pressed. "
            f"Kept <b>{esc(interaction.get('kept', 0))}</b> tests from <b>{esc(interaction.get('tries_used', 0))}</b> tries."
            + (f" Stopped early: {esc(interaction.get('stopped'))}." if interaction.get("stopped") else "")
            + ' <a href="auto_flows.json">Reusable flows (JSON)</a></p>'
            + ("<h3>Findings to review</h3><ul>" + interaction_findings + "</ul>" if interaction_findings else "")
            + '<div class="table"><table><tr><th>What was tried</th><th>Outcome</th><th>Detail</th></tr>'
            + tried_rows + "</table></div></section>" + coverage_section)
    elif interaction.get("reason"):
        interaction_section = ('<section class="scope"><b>User-like testing was not used</b><p>'
                               + esc(interaction["reason"]) + "</p></section>")
    else:
        interaction_section = ""
    evidence = []
    for record in [*screens, *results]:
        path = record.get("screenshot")
        if not path or not path.startswith("screenshots/") or ".." in path.split("/") or not path.endswith(".png"):
            continue
        caption = record.get("screen_name") or record.get("title") or record.get("id")
        evidence.append(
            '<a class="shot" href="'
            + esc(path)
            + '"><img loading="lazy" src="'
            + esc(path)
            + '"><span>'
            + esc(caption)
            + "</span></a>"
        )
    contract_evidence = "".join(
        "<li><pre>" + esc(json.dumps(record, ensure_ascii=False)) + "</pre></li>"
        for record in summary.get("contract_evidence", [])
    )
    recovery = "".join(
        "<tr><td>"
        + esc(entry.get("id"))
        + "</td><td><code>"
        + esc(entry.get("original_locator"))
        + "</code></td><td><code>"
        + esc(entry.get("replacement_locator"))
        + "</code></td><td>"
        + esc(entry.get("evidence"))
        + "</td><td>"
        + esc(entry.get("rerun_outcome"))
        + "</td></tr>"
        for entry in healing
    )
    controls = [(screen, element) for screen in screens for element in screen["elements"]]
    inventory = "".join(
        "<tr><td>" + esc(screen["screen_name"]) + "</td><td>"
        + esc(element.get("accessibility_id") or element.get("text") or element.get("resource_id") or "Control")
        + "</td><td>" + esc(element.get("type")) + "</td><td><code>"
        + esc(json.dumps(element.get("locators", []))) + "</code></td><td>"
        + esc(", ".join(option.get("label") or option.get("text", "") for option in element.get("options", [])))
        + "</td></tr>" for screen, element in controls[:500]
    )
    unvisited = "".join(
        "<li>" + esc(item.get("label")) + " ? " + esc(item.get("reason")) + "</li>"
        for item in summary["coverage"].get("unvisited", [])
    )
    ai_warning = ('<section class="scope"><b>AI failed or its output was rejected; fallback used</b><ul>'
                  + ''.join('<li>' + esc(warning) + '</li>' for warning in summary.get("ai_warnings", []))
                  + '</ul><p>Passing app checks do not verify the selected AI provider.</p></section>'
                  if summary.get("ai_warnings") else '')
    incomplete_warning = ('<section class="scope"><b>Run incomplete</b><p>'
                          + esc(summary.get("incomplete_reason") or "Some planned checks were not completed.")
                          + '</p><p>Passing checks do not mean the whole app was tested.</p></section>'
                          if summary.get("incomplete") else '')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qpilot ? Android evidence report</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f7fb;color:#18223a;font:15px/1.6 system-ui,sans-serif}}
main{{max-width:1200px;margin:auto;padding:32px}}header{{padding:28px;border-radius:20px;background:#121d39;color:white}}
header p{{color:#d7def0}}h1{{font-size:30px;margin:4px 0}}h2{{margin-top:28px}}.brand{{letter-spacing:3px;font-size:12px;color:#b7b5ff}}
.verdict{{display:inline-block;background:{color};padding:8px 16px;border-radius:30px;font-weight:700}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}}
.metric,section,.finding{{background:white;border:1px solid #e1e6f0;border-radius:14px;padding:18px}}.metric b{{display:block;font-size:30px}}.metric span,small{{color:#63708a}}small{{display:block}}
section{{margin:16px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:12px;border-bottom:1px solid #e5e9f2;text-align:left;vertical-align:top}}
th{{background:#f6f8fc}}.table{{overflow-x:auto}}.badge{{white-space:nowrap;border-radius:20px;background:#edf0ff;padding:4px 10px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}code{{overflow-wrap:anywhere}}a{{color:#5145ce}}.actions a{{display:inline-block;margin-right:12px}}
.gallery{{display:flex;gap:16px;overflow-x:auto;padding:10px 0}}.shot{{min-width:180px;max-width:220px;text-decoration:none}}.shot img{{width:100%;border:1px solid #ddd;border-radius:12px}}.shot span{{display:block}}
.scope{{border-left:4px solid #6e65df}}.stop{{border-left-color:#c2410c}}@media(max-width:600px){{main{{padding:12px}}header{{padding:20px}}}}
</style></head><body><main><header><div class="brand">BLOW AI / ANDROID</div><h1>Test results with evidence</h1>
<p>{esc(summary["package_name"])} ? Android {esc(summary["android_version"])} ? {esc(summary["device_id"])}</p>
<span class="verdict">{esc(summary["verdict"])}</span><p>{esc(" ".join(summary["reasons"]))}</p></header>
{bot_section}{early}{ai_warning}{incomplete_warning}<div class="metrics">{cards}</div>{interaction_section}<section class="scope"><b>Coverage has limits</b><p>Only discovered controls and approved expectations were checked.
Blocked, inferred and unexplored functionality is not counted as passed. A changed observed label needs review; business correctness requires explicit requirements.</p>
<p>{summary["coverage"]["tested"]} controls have passing execution evidence across {summary["screens_visited"]} inspected screens. No whole-app accuracy percentage is claimed.</p></section>
<p>Configured functional checks passed: <b>{summary.get('functional_checks', {}).get('passed', 0)}</b>. UI checks passed: <b>{summary.get('ui_checks', {}).get('passed', 0)}</b>. Observed controls still needing functional checks: <b>{summary.get('controls_needing_functional_checks_count', 0)}</b>.</p>
<p class="actions"><a href="test_cases.xlsx">Download Excel results</a><a href="test_cases.json">Test cases JSON</a><a href="results.json">Execution evidence</a><a href="summary.json">Run summary</a><a href="features.json">Feature coverage JSON</a></p>
{controls_section}<section><h2>Quality gates</h2><div class="table"><table><tr><th>Gate</th><th>Status</th><th>Evidence</th></tr>{gates}</table></div></section>
<section><h2>Test cases</h2><p>Scenario source / script source distinguishes actual AI output from rules and templates.</p><div class="table"><table><tr><th>Case</th><th>Result</th><th>Expected behavior</th><th>Generation source</th></tr>{rows}</table></div></section>
<section id="inventory"><h2>Control inventory</h2><p>Showing {min(500, len(controls))} of {len(controls)} recorded controls. Input values are omitted. Copy observed locators when building approved test flows. <a href="screens.json">Full inventory JSON</a></p><div class="table"><table><tr><th>Screen</th><th>Component</th><th>Type</th><th>Locators</th><th>Dropdown choices</th></tr>{inventory}</table></div></section>
<section><h2>Failure analysis</h2>{findings or "<p>No unresolved execution finding was recorded.</p>"}</section>
<section><h2>Captured evidence</h2><p>Screenshots containing entered input values or an external app are omitted.</p><div class="gallery">{"".join(evidence) or "<p>No screenshot was available.</p>"}</div></section>
<section><h2>Device recovery</h2><p>Platform recovery is recorded separately from passing app checks.</p><pre>{esc(json.dumps(summary.get("platform_recoveries", [])))}</pre></section>
<section><h2>Business and backend evidence</h2><ul>{contract_evidence or "<li>No business or backend contract was executed.</li>"}</ul></section>
<section><h2>Locator recovery</h2><div class="table"><table><tr><th>Case</th><th>Original</th><th>Replacement</th><th>Reason</th><th>Outcome</th></tr>{recovery}</table></div><p>Recovery changes only the locator. Approved assertions remain unchanged.</p></section>
<section><h2>Identified controls left unexplored</h2><ul>{unvisited or "<li>No additional control was recorded as unexplored.</li>"}</ul></section>
<footer>Run {esc(summary["run_id"])} ? App version {esc(summary.get("application_version")) or "unknown"} ? UiAutomator2 ? {esc(summary.get("duration_s"))} seconds</footer>
</main></body></html>"""
