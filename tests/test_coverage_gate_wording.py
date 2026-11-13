"""Partial exploration must not make route/coverage gates claim exhaustive reachability.
Consistency failures surface in summary reasons; provisional findings keep Insufficient Evidence.
"""
from backend.agents.reporter import consistency_reasons, decide_verdict, quality_gates
from backend.page_status import exploration_status


def _page(url="https://app.test/", status=200):
    return {"url": url, "slug": "home", "status": status, "title": "Home"}


def test_routes_gate_avoids_exhaustive_claim_when_pending_or_interaction_limited():
    crawl = {
        "visited": 3, "not_visited_count": 4, "limit_reached": True, "limit": 3,
        "actions": {"not_tried_limit": 5},
        "exploration": exploration_status({
            "visited": 3, "not_visited_count": 4, "limit_reached": True,
            "actions": {"not_tried_limit": 5}}),
    }
    state = {
        "app_map": [_page(), _page("https://app.test/a"), _page("https://app.test/b")],
        "results": [{"nodeid": "t.py::ok", "test": "ok", "outcome": "passed", "file": "t.py"}],
        "failures": [], "login": {}, "crawl": crawl, "test_cases": [], "healing_log": [], "log": [],
    }
    gates = {g["id"]: g for g in quality_gates(state)}
    routes = gates["routes"]
    assert routes["status"] == "risk"
    assert "every reachable" not in routes["name"].lower()
    detail = routes["detail"].lower()
    assert "exhaustive" in detail and "not" in detail
    assert "pending" in detail or "not visited" in detail or "partial" in detail


def test_time_or_action_limit_alone_marks_routes_partial():
    crawl = {
        "visited": 2, "not_visited_count": 0, "time_limit_reached": True,
        "actions": {"not_tried_limit": 3},
        "exploration": {"status": "partial", "within_selected_scope": False, "actions_limited": True},
    }
    state = {
        "app_map": [_page(), _page("https://app.test/a")],
        "results": [{"nodeid": "t.py::ok", "test": "ok", "outcome": "passed", "file": "t.py"}],
        "failures": [], "login": {}, "crawl": crawl, "test_cases": [], "healing_log": [], "log": [],
    }
    routes = next(g for g in quality_gates(state) if g["id"] == "routes")
    assert routes["status"] == "risk"
    assert "exhaustive reachability" in routes["detail"].lower() or "partial" in routes["detail"].lower()


def test_consistency_reasons_lead_when_metrics_inconsistent():
    m = {"consistent": False, "consistency": [
        {"ok": False, "check": "Every failed or inconclusive single test has its finding",
         "detail": "3 failed; 0 covered"},
        {"ok": True, "check": "ok", "detail": "fine"},
    ]}
    reasons = consistency_reasons(m)
    assert reasons and "consistency FAILED" in reasons[0]
    assert "Every failed" in reasons[0]
    assert consistency_reasons({"consistent": True, "consistency": []}) == []


def test_provisional_findings_keep_insufficient_evidence_not_zero_bugs():
    page = _page()
    results = [
        {"nodeid": "t.py::fail", "test": "fail", "outcome": "failed", "file": "t.py",
         "error_type": "AssertionError", "error": "bad"},
        {"nodeid": "t.py::ok", "test": "ok", "outcome": "passed", "file": "t.py"},
    ]
    failures = [{
        "id": 0, "source": "test", "nodeid": "t.py::fail", "test": "fail", "file": "t.py",
        "category": "product_defect", "severity": "high", "confidence": "medium",
        "explanation": "provisional assert failure", "provisional": True,
    }]
    state = {"app_map": [page], "results": results, "failures": failures, "login": {}, "crawl": {},
             "test_cases": [], "healing_log": [], "log": []}
    gates = {g["id"]: g for g in quality_gates(state)}
    assert gates["blockers"]["status"] == "missing"
    assert "insufficient evidence" in gates["blockers"]["detail"].lower()
    assert "provisional" in gates["blockers"]["detail"].lower() or "untriaged" in gates["blockers"]["detail"].lower()
    # Must not clear the gate with a "no bugs" style pass detail
    assert gates["blockers"]["detail"].lower().strip() not in ("none found.", "none found", "none.")
    verdict, reasons, _ = decide_verdict(state)
    assert verdict == "Insufficient Evidence"
    assert not any(r.lower().strip() in ("none found.", "none found", "none.") for r in reasons)
