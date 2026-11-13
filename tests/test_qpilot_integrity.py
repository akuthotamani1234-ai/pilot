"""Historical evidence and interrupted worker recovery must remain truthful without AI."""
import hashlib
import json
from pathlib import Path

import pytest

from backend.finalization import reconcile
from backend.report_rebuild import rebuild

RUNS = Path(__file__).resolve().parents[1] / "runs"


def _row(name, outcome="failed"):
    return {"nodeid": f"test_flow.py::test_{name}", "test": f"test_{name}", "file": "test_flow.py",
            "outcome": outcome, "checks": 1, "error": "AssertionError: Expected result was not observed"}


def test_worker_results_survive_torn_lines_and_optional_analysis(tmp_path):
    result = _row("one")
    (tmp_path / "results.gw0.jsonl").write_text(json.dumps(result) + '\n{"unfinished":', encoding="utf-8")
    case = {"id": "one", "tc_id": "TC-one", "tests": ["test_one"], "files": ["test_flow.py"]}
    state = {"run_dir": str(tmp_path), "test_cases": [case], "failures": []}
    first = reconcile(state)
    second = reconcile(first)
    assert first["results"] == second["results"] and len(second["failures"]) == 1
    assert second["failures"][0]["category"] == "untriaged"
    assert second["test_cases"][0]["finding_ids"] == [second["failures"][0]["finding_id"]]
    assert second["test_cases"][0]["execution_status"] == "Failed"


def test_grouped_findings_retain_every_node_and_case(tmp_path):
    from backend.agents.failure_analysis import _one_per_problem
    rows = [_row("no_console_errors_a"), _row("no_console_errors_b")]
    findings = [{"source": "test", "nodeid": r["nodeid"], "test": r["test"], "category": "product_defect",
                 "error": "Same JS error", "explanation": "Same error", "evidence": [], "page_url": str(i)}
                for i, r in enumerate(rows)]
    grouped = _one_per_problem(findings)
    assert set(grouped[0]["nodeids"]) == {r["nodeid"] for r in rows}
    cases = [{"id": str(i), "tc_id": str(i), "files": ["test_flow.py"], "tests": [r["test"]]} for i, r in enumerate(rows)]
    state = reconcile({"run_dir": str(tmp_path), "results": rows, "failures": grouped, "test_cases": cases})
    assert len(state["failures"]) == 1 and set(state["failures"][0]["case_ids"]) == {"0", "1"}


def test_analysis_can_replace_results_but_report_recovery_ingests_saved_workers(tmp_path):
    previous, current = _row("previous"), _row("current")
    (tmp_path / "results.json").write_text(json.dumps([previous]), encoding="utf-8")
    state = {"run_dir": str(tmp_path), "results": [current]}
    assert [r["nodeid"] for r in reconcile(state, recover=False, save=False)["results"]] == [current["nodeid"]]
    assert len(reconcile(state, save=False)["results"]) == 2


def test_rejected_ai_proposals_remain_in_planned_cases(tmp_path, monkeypatch):
    from backend.agents import script_generator as gen
    monkeypatch.setattr(gen, "_llm_flows_in_batches", lambda *a: ("", ["ai_flow_1"], "Business record was not observed"))
    case = {"id": "ai_flow_1", "title": "Unsupported record", "kind": "flow", "ai": True, "pages": [], "files": ["test_flows_ai.py"]}
    cases, _ = gen._generate({"run_dir": str(tmp_path), "app_map": []}, {}, [case], lambda *a: None, [], [])
    assert len(cases) == 1 and cases[0]["unsupported"] is True
    assert "not observed" in cases[0]["skip_reason"] and cases[0]["files"] == []


@pytest.mark.parametrize("folder,total,adverse", [
    ("opensource-demo.orangehrmlive.com_20261112_230110", 123, 41),
    ("demoblaze.com_20261113_131702", 124, 4),
    ("demoblaze.com_20261113_134616", 0, 0),
])
def test_saved_reports_rebuild_without_mutating_evidence(tmp_path, folder, total, adverse):
    source = RUNS / folder
    if not source.is_dir():
        pytest.skip("Local immutable evidence is not part of the source distribution")
    tracked = [p for p in source.iterdir() if p.is_file() and p.suffix in {".json", ".log", ".html"}]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    result = rebuild(source, tmp_path / "rebuilt")
    assert result["after"]["single_tests"]["total"] == total
    assert result["after"]["consistent"] is True
    findings = json.loads((tmp_path / "rebuilt" / "failures.json").read_text(encoding="utf-8"))
    covered = {node for f in findings if f.get("source") == "test" for node in f.get("nodeids") or [f["nodeid"]]}
    assert len(covered) == adverse
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in hashes.items())
    summary = json.loads((tmp_path / "rebuilt" / "summary.json").read_text(encoding="utf-8"))
    if adverse == 41:
        assert next(g for g in summary["gates"] if g["id"] == "automation")["status"] != "pass"
        assert result["after"]["cases"]["planned"] == 245
    if total == 0:
        assert summary["verdict"] == "Insufficient Evidence"
        assert summary["exploration"]["status"] == "partial"


def test_rebuild_refuses_historical_output():
    source = RUNS / "demoblaze.com_20261113_131702"
    with pytest.raises(ValueError):
        rebuild(source, source)
