"""Interrupted / incomplete runs must still produce a finding for every failed or inconclusive result
before gates and reports (OrangeHRM-style: many failures, empty findings.json → metrics.consistent false).

Prompt baseline (immutable): 123 single-test results → 79 pass, 35 fail, 6 inconclusive, 3 skipped
(41 failed+inconclusive) with 0 findings. Empty findings must never clear reliability / bug-absence gates.
"""
import json
from pathlib import Path

from backend import metrics
from backend.agents.failure_analysis import ensure_findings_from_results, load_saved_results
from backend.agents.reporter import decide_verdict, quality_gates


def _result(nodeid: str, test: str, outcome: str, **kw) -> dict:
    return dict({"nodeid": nodeid, "test": test, "file": "test_home.py", "outcome": outcome,
                 "error_type": kw.pop("error_type", ""), "error": kw.pop("error", "")}, **kw)


def _fixture_results() -> list[dict]:
    return [
        _result("test_home.py::test_fail_assert", "test_fail_assert", "failed",
                error_type="AssertionError", error="E   AssertionError: Empty form was accepted"),
        _result("test_home.py::test_fail_timeout", "test_fail_timeout", "failed",
                error_type="TimeoutError", error="Timeout 30000ms exceeded"),
        _result("test_home.py::test_inconclusive", "test_inconclusive", "inconclusive",
                error="Inconclusive: the test checked nothing"),
        _result("test_home.py::test_ok", "test_ok", "passed"),
    ]


def _write_run(tmp: Path, results: list[dict], failures: list | None = None) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (tmp / "failures.json").write_text(json.dumps(failures if failures is not None else [], indent=2),
                                       encoding="utf-8")
    return tmp


def test_ensure_findings_creates_one_per_failed_or_inconclusive(tmp_path):
    run = _write_run(tmp_path / "run", _fixture_results(), failures=[])
    findings = ensure_findings_from_results(run)
    assert len(findings) == 3
    by_node = {f["nodeid"]: f for f in findings}
    assert by_node["test_home.py::test_fail_assert"]["category"] == "product_defect"
    assert by_node["test_home.py::test_fail_timeout"]["category"] == "timeout"
    assert by_node["test_home.py::test_inconclusive"]["category"] == "inconclusive"
    assert all(f.get("provisional") for f in findings)
    saved = json.loads((run / "failures.json").read_text(encoding="utf-8"))
    assert len(saved) == 3
    m = metrics.build(_fixture_results(), [], None, findings)
    cover = next(c for c in m["consistency"] if c["check"].startswith("Every failed or inconclusive"))
    assert cover["ok"], cover
    assert m["consistent"] or all(
        c["ok"] for c in m["consistency"] if c["check"].startswith("Every failed or inconclusive"))


def test_ensure_findings_is_idempotent_and_keeps_richer_findings(tmp_path):
    results = _fixture_results()
    rich = [{"id": 0, "source": "test", "nodeid": "test_home.py::test_fail_assert", "test": "test_fail_assert",
             "file": "test_home.py", "category": "product_defect", "category_name": "Application defect",
             "severity": "high", "confidence": "high", "explanation": "LLM-enriched explanation",
             "ai_explanation": "Plain English from the model", "error": "Empty form was accepted",
             "bug": {"title": "Empty form", "severity": "high"}}]
    run = _write_run(tmp_path / "run", results, failures=rich)
    first = ensure_findings_from_results(run, results)
    assert len(first) == 3
    kept = next(f for f in first if f["nodeid"] == "test_home.py::test_fail_assert")
    assert kept.get("ai_explanation") == "Plain English from the model" and kept.get("bug")
    assert not kept.get("provisional")
    second = ensure_findings_from_results(run, results)
    assert len(second) == 3
    assert [f["nodeid"] for f in second] == [f["nodeid"] for f in first]


def test_load_saved_results_prefers_json_then_jsonl(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    rows = _fixture_results()[:2]
    (run / "results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert len(load_saved_results(run)) == 2
    (run / "results.json").write_text(json.dumps(rows + [_fixture_results()[2]], indent=2), encoding="utf-8")
    assert len(load_saved_results(run)) == 3


def test_empty_findings_do_not_claim_zero_unreliable_or_no_bugs():
    page = {"url": "https://hr.test/", "slug": "home", "status": 200, "title": "Home"}
    results = _fixture_results()
    state = {"app_map": [page], "results": results, "failures": [], "login": {}, "crawl": {},
             "test_cases": [], "healing_log": [], "log": []}
    gates = {g["id"]: g for g in quality_gates(state)}
    assert gates["automation"]["status"] == "missing"
    assert not gates["automation"]["detail"].startswith("0 of")
    assert "no linked finding" in gates["automation"]["detail"]
    assert gates["blockers"]["status"] == "missing"
    assert "no finding" in gates["blockers"]["detail"].lower()
    verdict, _, _ = decide_verdict(state)
    assert verdict == "Insufficient Evidence"


def test_report_path_ensure_then_gates_see_findings(tmp_path):
    """Rebuild/report path: after ensure_findings, gates no longer pretend 0 unreliable tests with empty failures."""
    results = _fixture_results()
    run = _write_run(tmp_path / "run", results, failures=[])
    findings = ensure_findings_from_results(run, results)
    page = {"url": "https://hr.test/", "slug": "home", "status": 200, "title": "Home"}
    state = {"app_map": [page], "results": results, "failures": findings, "login": {}, "crawl": {},
             "test_cases": [], "healing_log": [], "log": [], "run_dir": str(run)}
    gates = {g["id"]: g for g in quality_gates(state)}
    # timeout + inconclusive are unreliable answers; product_defect is a real finding - never "0 of N"
    assert gates["automation"]["status"] in ("missing", "risk")
    assert not gates["automation"]["detail"].startswith("0 of")
    assert gates["blockers"]["status"] == "fail"  # empty-form assertion → product_defect blocker
    m = metrics.build(results, [], None, findings)
    assert next(c for c in m["consistency"] if "finding" in c["check"])["ok"]
