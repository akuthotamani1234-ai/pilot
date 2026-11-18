"""Apply the Qpilot X rules to one finished run.

The listing sample is not changed here. These rules read the run's own pages,
failures, roles, and optional files, then write the decisions. A trend does not
replace the run's verdict.
"""
import json
from pathlib import Path

from .agent_eval import evaluate, model_change_allowed
from .coverage_verify import verify_sources
from .dependency_fault import inject_fault
from .device_matrix import evaluate_matrix
from .discovery_graph import write_graph
from .enterprise import readiness as enterprise_readiness
from .env_controls import CONTROLS, action_still_blocked, enable_control
from .explore_score import rank_candidates
from .human_review import decide
from .journey_map import compare_journey
from .locale_check import check_locale, keep_sample
from .mutation_score import score_planted
from .ops_readiness import readiness as ops_readiness
from .oracle import bind_assertion, cart_expected, decide_observation
from .plugins import review_plugin
from .portfolio_capture import capture_portfolios
from .portfolio_gates import evaluate_portfolios
from .quality_trends import cluster_runs, keep_verdict
from .release_row import from_run
from .replay_pack import replay
from .schema_diff import diff_specs
from .sessions import RoleBook
from .surface_coverage import summarize_surfaces

_CART_WORDS = ("cart", "add to cart", "add-to-cart")


def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _sessions(run_id: str, roles: dict) -> dict:
    book = RoleBook(run_id or "run")
    for name, info in (roles or {}).items():
        if not isinstance(info, dict):
            continue
        book.add_role(str(name), f"vault:{name}")
        pages = info.get("pages") or {}
        if isinstance(pages, dict):
            for url, result in pages.items():
                book.record_access(str(name), str(url), str(result).lower() in {"ok", "opened"})
        if str(info.get("login") or "").lower() in {"expired", "session_expired"}:
            book.expire(str(name))
    return book.public()


def _replay_packages(failures: list[dict], results: list[dict], environment: str) -> list[dict]:
    by_node = {row.get("nodeid"): row for row in results}
    packages = []
    for failure in failures:
        node = failure.get("nodeid")
        result = by_node.get(node) or {}
        screenshots = [item for item in (result.get("screenshot"), result.get("trace")) if item]
        package = {
            "environment": environment or "test",
            "build": failure.get("file") or "unknown",
            "browser": "chromium",
            "seed": node or failure.get("test") or "0",
            "starting_state": {"url": failure.get("page_url") or failure.get("url") or ""},
            "test_data": {"test": failure.get("test") or ""},
            "actions": [failure.get("test") or "rerun the failed test"],
            "network": failure.get("network") or ["recorded"],
            "screenshots": screenshots,
            "assertion": (failure.get("error") or failure.get("explanation") or "")[:500],
        }
        packages.append({"nodeid": node or "", "replay": replay(package)})
    return packages


def _cart_checks(cases: list[dict]) -> list[dict]:
    checks = []
    for case in cases:
        text = " ".join(str(case.get(key) or "") for key in ("title", "kind", "feature")).lower()
        if not any(word in text for word in _CART_WORDS):
            continue
        spec = case.get("spec") if isinstance(case.get("spec"), dict) else {}
        fields = {name: spec.get(name) or case.get(name) for name in
                  ("item", "price", "tax", "discount", "quantity", "fulfillment")}
        source = str(case.get("expected_source") or case.get("oracle") or "")
        ok, reason = cart_expected(source, fields)
        statement = str(case.get("expected") or case.get("title") or "cart check")
        assertion = bind_assertion(
            source=source or "ai",
            statement=statement,
            scope=str(case.get("url") or case.get("page") or "/cart"),
            requirement_id=str(case.get("tc_id") or case.get("id") or ""),
        )
        observed = str(case.get("actual_result") or case.get("execution_status") or "")
        matched = ok and str(case.get("execution_status") or "").lower() in {"passed", "pass"}
        decision = decide_observation(assertion, observed=observed, matched=matched)
        checks.append({
            "id": case.get("tc_id") or case.get("id") or "",
            "ok": ok,
            "reason": reason,
            "assertion": assertion,
            "decision": decision,
        })
    return checks


def _outcome(row: dict) -> str:
    status = str(row.get("status") or row.get("execution_status") or row.get("outcome") or "").lower()
    if status in {"passed", "pass"}:
        return "passed"
    if status in {"failed", "fail", "error"}:
        return "failed"
    if status in {"blocked"}:
        return "blocked"
    if status in {"skipped", "inconclusive", "flaky"}:
        return "blocked"
    return ""


def _device_evidence(state: dict, results: list[dict]) -> list[dict]:
    """Build Gate D evidence rows from this run only — never invent unverified profiles."""
    evidence = []
    target = str(state.get("target_type") or "web").lower()
    outcomes = [_outcome(row) for row in results if _outcome(row)]
    if not outcomes:
        return evidence
    primary = outcomes[0]
    if target in {"web", ""}:
        evidence.append({"surface": "web", "viewport": "1366x900", "outcome": primary})
        if any("mobile" in str(row.get("nodeid") or row.get("file") or "").lower()
               or "phone" in str(row.get("title") or "").lower() for row in results):
            evidence.append({"surface": "web", "viewport": "390x844", "outcome": primary})
    if target in {"mobile", "android"}:
        config = state.get("config") if isinstance(state.get("config"), dict) else {}
        evidence.append({
            "surface": "android",
            "device_id": str(config.get("device_id") or ""),
            "form": "emulator" if str(config.get("device_id") or "").startswith("emulator-") else "",
            "api_level": config.get("api_level") or config.get("android_version"),
            "outcome": primary,
        })
    return evidence


def _portfolios(run_dir: Path, locale_payload: dict) -> dict:
    visual = _read_json(run_dir / "visual.json")
    timings = _read_json(run_dir / "performance.json")
    headers = _read_json(run_dir / "security_headers.json")
    a11y_page = _read_json(run_dir / "a11y_page.json")
    https = None
    if isinstance(headers, dict) and "https" in headers:
        https = bool(headers.get("https"))
        headers = headers.get("headers") if isinstance(headers.get("headers"), dict) else {
            k: v for k, v in headers.items() if k != "https"
        }
    observed = locale_payload.get("observed") if isinstance(locale_payload.get("observed"), dict) else None
    expected = locale_payload.get("expected") if isinstance(locale_payload.get("expected"), dict) else None
    return evaluate_portfolios(
        a11y_page=a11y_page if isinstance(a11y_page, dict) else None,
        visual_report=visual if isinstance(visual, dict) else None,
        timings=timings if isinstance(timings, dict) else None,
        locale_observed=observed,
        locale_expected=expected,
        security_headers=headers if isinstance(headers, dict) else None,
        https=https,
    )


def _plugins(root: Path) -> list[dict]:
    folder = root / "plugins"
    if not folder.is_dir():
        return []
    reviewed = []
    for path in sorted(folder.glob("*.json")):
        payload = _read_json(path)
        if isinstance(payload, dict):
            reviewed.append({"file": path.name, **review_plugin(payload)})
    return reviewed


def _schema(run_dir: Path, baseline: Path | None) -> dict:
    current = _read_json(run_dir / "api_spec.json")
    previous = _read_json(run_dir / "api_spec_previous.json")
    if previous is None and baseline is not None:
        previous = _read_json(baseline / "api_spec.json")
    if not isinstance(current, dict) or not isinstance(previous, dict):
        return {"compared": False, "broken": []}
    diff = diff_specs(previous, current)
    diff["compared"] = True
    return diff


def _mutation(run_dir: Path, failures: list[dict]) -> dict:
    planted = _read_json(run_dir / "planted.json")
    if not isinstance(planted, list):
        return {"scored": False, "caught": [], "missed": [], "false_reports": [], "qpilot_defects": []}
    reported = [str(item.get("id") or item.get("tc_id") or "") for item in failures if item.get("id") or item.get("tc_id")]
    score = score_planted([row for row in planted if isinstance(row, dict)], reported)
    score["scored"] = True
    return score


def _locale(run_dir: Path, sample: int, catalog: int) -> dict:
    payload = _read_json(run_dir / "locale.json")
    if not isinstance(payload, dict):
        return {"checked": False, "sample": keep_sample(sample, catalog)}
    observed = payload.get("observed") if isinstance(payload.get("observed"), dict) else {}
    expected = payload.get("expected") if isinstance(payload.get("expected"), dict) else {}
    result = check_locale(observed, expected)
    result["checked"] = True
    result["sample"] = keep_sample(sample, catalog)
    return result


def _journeys(run_dir: Path) -> list[dict]:
    payload = _read_json(run_dir / "journeys.json")
    if not isinstance(payload, list):
        return []
    compared = []
    for journey in payload:
        if not isinstance(journey, dict):
            continue
        steps = journey.get("steps") if isinstance(journey.get("steps"), dict) else {}
        compared.append(compare_journey(
            str(journey.get("id") or ""),
            {str(name): list(value) for name, value in steps.items() if isinstance(value, list)},
            must_match=bool(journey.get("must_match")),
        ))
    return compared


def _trends(run_dir: Path, verdict: str, failures: list[dict]) -> dict:
    runs = [{"verdict": verdict, "failures": [str(item.get("category") or item.get("page_url") or "")
             for item in failures if item.get("category") or item.get("page_url")], "flaky": []}]
    parent = run_dir.parent
    if parent.is_dir():
        for path in sorted(parent.glob("*/summary.json")):
            if path.parent == run_dir:
                continue
            summary = _read_json(path)
            if isinstance(summary, dict) and isinstance(summary.get("qx_areas"), list):
                runs.append({"verdict": summary.get("verdict") or "", "failures": summary.get("qx_areas") or [],
                             "flaky": []})
    trends = cluster_runs(runs)
    trends["verdict"] = keep_verdict(verdict, trends)
    return trends


def _heals(healing_log: list[dict], answers: dict) -> list[dict]:
    waiting = []
    for entry in healing_log:
        if not entry.get("proposal"):
            continue
        answer = answers.get(entry.get("nodeid") or "")
        text = answer.get("answer") if isinstance(answer, dict) else answer
        decision = decide("heal", text if entry.get("accepted") else None)
        waiting.append({"nodeid": entry.get("nodeid") or "", "apply": decision["apply"], "reason": decision["reason"],
                        "original_error": entry.get("original_error") or entry.get("error") or ""})
    return waiting


def apply_run(state: dict, *, root: Path | None = None) -> dict:
    """Run every blueprint rule against this run and return the decisions."""
    run_dir = Path(state.get("run_dir") or ".")
    environment = str(state.get("environment") or "test")
    crawl = state.get("crawl") or {}
    swarm = crawl.get("swarm") or {}
    app_map = state.get("app_map") or []
    failures = list(state.get("failures") or [])
    results = list(state.get("results") or [])
    cases = list(state.get("test_cases") or [])
    sample = int(swarm.get("sample") or 0)
    catalog = sum(len((page.get("itemLinks") or {}).get("links") or []) for page in app_map)
    candidates = [{
        "url": page.get("url") or "",
        "new_template": False,
        "failed": bool(page.get("error")),
        "uncertain": bool(page.get("still_loading")),
        "changed": False,
        "journey_distance": int(page.get("depth") or 0),
    } for page in app_map]
    ranked = rank_candidates(candidates)
    visited = [page.get("url") or "" for page in app_map if page.get("url")]
    blocked = [row.get("url") or row for row in (crawl.get("blocked_requests") or [])]
    blocked = [item if isinstance(item, str) else str(item.get("url") or "") for item in blocked]
    requirements = [line.strip() for line in str(state.get("requirements") or "").splitlines() if line.strip()]
    baseline = Path(state["changes"]["baseline_dir"]) if (state.get("changes") or {}).get("baseline_dir") else None
    fault_name = str(state.get("dependency_fault") or "")
    fault = inject_fault(environment, fault_name, permitted=bool(state.get("dependency_permitted"))) if fault_name else {
        "injected": False, "reason": "no dependency fault was requested"}
    pay_blocked, pay_reason = action_still_blocked("pay")
    controls = {name: enable_control(environment, name)[0] for name in sorted(CONTROLS)}
    evaluation = evaluate([{
        "id": row.get("nodeid") or row.get("test") or "",
        "expected": "passed",
        "actual": "passed" if str(row.get("status") or "").lower() == "passed" else "other",
        "failed": str(row.get("status") or "").lower() not in {"passed", "skipped"},
        "unsupported": False,
        "cost": 0,
    } for row in results])
    stored_change, stored_reason = model_change_allowed(evaluation)
    verdict = str(state.get("verdict") or "")
    locale = _locale(run_dir, sample, catalog)
    locale_raw = _read_json(run_dir / "locale.json")
    locale_file = locale_raw if isinstance(locale_raw, dict) else {}
    capture_portfolios(run_dir, app_map, source_url=str(state.get("url") or ""))
    applied = {
        "sample_unchanged": True,
        "sample": sample,
        "explore": {"next": [{"url": row.get("url"), "score": row.get("score")} for row in ranked[:30]]},
        "coverage": verify_sources(graph=visited, dom=visited, routes=list(crawl.get("not_visited") or []),
                                   blocked=[item for item in blocked if item], requirements=requirements),
        "oracle": _cart_checks(cases),
        "sessions": _sessions(str(state.get("run_id") or run_dir.name), state.get("roles") or {}),
        "environment": {"controls": controls, "payment_blocked": pay_blocked, "payment_reason": pay_reason},
        "replay": _replay_packages(failures, results, environment),
        "mutation": _mutation(run_dir, failures),
        "journeys": _journeys(run_dir),
        "locale": locale,
        "evaluation": {**evaluation, "model_change_allowed": stored_change, "reason": stored_reason},
        "incremental": (state.get("changes") or {}).get("incremental") or {},
        "dependency": fault,
        "schema": _schema(run_dir, baseline),
        "review": _heals(list(state.get("healing_log") or []), {}),
        "trends": _trends(run_dir, verdict, failures),
        "plugins": _plugins(root or Path(".")),
        "device_matrix": evaluate_matrix(_device_evidence(state, results)),
        "portfolios": _portfolios(run_dir, locale_file),
        "enterprise": enterprise_readiness(),
        "ops": ops_readiness(),
        "discovery_graph": write_graph(run_dir, app_map, crawl),
        "surfaces": summarize_surfaces(app_map, crawl),
    }
    applied["trends"]["verdict"] = keep_verdict(verdict, applied["trends"])
    applied["release"] = from_run(state)
    (run_dir / "portfolio_gates.json").write_text(
        json.dumps(applied["portfolios"], indent=2), encoding="utf-8")
    (run_dir / "surface_coverage.json").write_text(
        json.dumps(applied["surfaces"], indent=2), encoding="utf-8")
    return applied


def write_applied(state: dict, *, root: Path | None = None) -> dict:
    """Apply the rules and store them beside the report. The verdict is kept."""
    applied = apply_run(state, root=root)
    run_dir = Path(state.get("run_dir") or ".")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "qx_applied.json").write_text(json.dumps(applied, indent=2), encoding="utf-8")
    return applied
