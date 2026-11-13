"""P9 evidence linkage / classification and P6 run-time reserves (OrangeHRM hardening).

Offline only: no device, network, or AI.
"""
import json
import time
from pathlib import Path

from backend import runctl
from backend.agents.failure_analysis import classify, ensure_findings_from_results
from backend.config import settings


def _result(nodeid: str, test: str, outcome: str, **kw) -> dict:
    return dict({"nodeid": nodeid, "test": test, "file": "test_home.py", "outcome": outcome,
                 "error_type": kw.pop("error_type", ""), "error": kw.pop("error", "")}, **kw)


def test_console_without_assertion_is_infrastructure_not_product_defect(tmp_path):
    """Screenshot + console error, no AssertionError → automation/infrastructure, not product_defect."""
    run = tmp_path / "run"
    run.mkdir()
    results = [_result(
        "test_home.py::test_open", "test_open", "failed",
        error_type="Error",
        error="Timeout while waiting for network; see console",
        screenshot="failure_screenshots/open.png",
        url="https://hr.test/pim/viewEmployeeList",
        warnings=["JS exception: TypeError: Cannot read properties of null"],
        console_errors=["Failed to load resource: net::ERR_CONNECTION_REFUSED"],
    )]
    (run / "results.json").write_text(json.dumps(results), encoding="utf-8")
    (run / "failures.json").write_text("[]", encoding="utf-8")
    findings = ensure_findings_from_results(run, results)
    assert len(findings) == 1
    f = findings[0]
    assert f["category"] == "infrastructure"
    assert f["category"] != "product_defect"
    assert f["screenshot"] == "failure_screenshots/open.png"
    assert f["page_url"] == "https://hr.test/pim/viewEmployeeList"
    assert f.get("console_notes") or f.get("network_notes")
    assert any("JS exception" in n or "ERR_" in n for n in (f.get("console_notes") or []) + (f.get("network_notes") or []))


def test_finding_retains_control_expected_observed_and_redacts(tmp_path, monkeypatch):
    from backend.safety import REDACTED

    monkeypatch.setenv("TEST_PASSWORD", "SuperSecretPw!")
    results = [_result(
        "test_checks.py::test_check_1", "test_check_1", "failed",
        error_type="AssertionError",
        error="E   AssertionError: Empty form was accepted",
        screenshot="shots/a.png",
        url="https://hr.test/pim/addEmployee",
        control="Employee Name",
        container="#addEmployeeForm",
        expected="Required validation message",
        observed="Empty form was accepted",
    )]
    cases = [{"tc_id": "TC-1", "title": "Add employee", "page": "pim", "url": "https://hr.test/pim/addEmployee",
              "feature": "PIM", "element": "Employee Name", "expected": "Required validation message",
              "steps": ["Open add employee"], "spec": {"form": "#addEmployeeForm", "name": "Employee Name"},
              "id": "form0", "kind": "form", "files": ["test_checks.py"]}]
    results[0]["tc_id"] = "TC-1"
    run = tmp_path / "run2"
    run.mkdir()
    (run / "test_cases.json").write_text(json.dumps(cases), encoding="utf-8")
    findings = ensure_findings_from_results(run, results, cases=cases)
    f = findings[0]
    assert f["control"] == "Employee Name"
    assert f["container"] == "#addEmployeeForm"
    assert f["expected"] == "Required validation message"
    assert "Empty form" in (f.get("observed") or "")
    assert f["screenshot"] == "shots/a.png"
    assert f["category"] == "product_defect"
    assert REDACTED not in (f.get("control") or "x")  # no secret leaked into control name


def test_session_expiry_not_auth_problem():
    """Protected reauth / session expiry is reported separately from broken credentials."""
    logged_out = (
        "Inconclusive: logged out - the website ended the test account's session (its login page came back), "
        "so this test says nothing about the page; signing in again did not work")
    cat, why, _ = classify(_result(
        "test_checks.py::test_x", "test_x", "inconclusive", error=logged_out))
    assert cat == "inconclusive"
    assert "session" in why.lower() or "reauth" in why.lower()
    assert "not a broken credential" in why.lower() or "auth_problem" in why.lower()

    auth_cat, _, _ = classify(_result(
        "test_flows.py::test_orders", "test_orders", "failed",
        error="AssertionError: 'Orders' sent me back to the login page"))
    assert auth_cat == "auth_problem"


def test_readiness_timeout_is_clear_timeout_category():
    cat, why, _ = classify(_result(
        "test_site.py::test_page", "test_page", "failed",
        error_type="TimeoutError",
        error="the page took too long to open; still loading / never finished loading"))
    assert cat == "timeout"
    assert "readiness" in why.lower() or "loading" in why.lower() or "time" in why.lower()


def test_reserve_stops_heavy_work_but_analysis_and_report_still_run(tmp_path, monkeypatch):
    """When remaining run budget is inside ANALYSIS+REPORT reserve, analysis/report still invoked."""
    runctl.reset()
    monkeypatch.setattr(settings, "analysis_reserve_s", 180)
    monkeypatch.setattr(settings, "report_reserve_s", 120)
    monkeypatch.setattr(runctl, "remaining_s", lambda: 50.0)  # below 300s reserve
    assert runctl.should_stop_heavy_work()
    assert not runctl.stopping()  # soft reserve only — hard stop not set

    run = tmp_path / "reserve_run"
    run.mkdir()
    results = [_result(
        "test_home.py::test_fail", "test_fail", "failed",
        error_type="AssertionError", error="E   AssertionError: Empty form was accepted",
        screenshot="s.png")]
    (run / "results.json").write_text(json.dumps(results), encoding="utf-8")
    (run / "failures.json").write_text("[]", encoding="utf-8")

    invoked = {"analysis": False, "report": False}

    def analysis():
        invoked["analysis"] = True
        return ensure_findings_from_results(run, results)

    def report(findings):
        invoked["report"] = True
        (run / "summary.json").write_text(json.dumps({
            "verdict": "Insufficient Evidence", "findings": len(findings),
            "reserve": True}), encoding="utf-8")
        return {"report_path": str(run / "summary.json"), "failures": findings}

    # Soft reserve must not block finalize: same contract as main incomplete / graph tail.
    assert runctl.should_stop_heavy_work()
    findings = analysis()
    out = report(findings)
    assert invoked == {"analysis": True, "report": True}
    assert findings and findings[0]["category"] == "product_defect"
    assert Path(out["report_path"]).exists()


def test_reserve_budget_helpers(monkeypatch):
    runctl.reset()
    monkeypatch.setattr(settings, "analysis_reserve_s", 10)
    monkeypatch.setattr(settings, "report_reserve_s", 5)
    assert runctl.reserve_budget_s() == 15
    runctl._started = time.time()
    runctl._limit_s = 1000
    monkeypatch.setattr(runctl, "remaining_s", lambda: 100.0)
    assert not runctl.should_stop_heavy_work()
    monkeypatch.setattr(runctl, "remaining_s", lambda: 10.0)
    assert runctl.should_stop_heavy_work()
    runctl.reset()
