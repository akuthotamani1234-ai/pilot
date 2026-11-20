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
    # Rule-based ensure_findings marks rows provisional → Insufficient Evidence, not “none found” / zero bugs
    assert gates["blockers"]["status"] == "missing"
    assert "provisional" in gates["blockers"]["detail"].lower() or "insufficient evidence" in gates["blockers"]["detail"].lower()
    assert "none found" not in gates["blockers"]["detail"].lower()
    m = metrics.build(results, [], None, findings)
    assert next(c for c in m["consistency"] if "finding" in c["check"])["ok"]


def test_a_finding_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = b"tenant-b-only-finding"
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_bytes(secret)
    (other / "failures.json").write_bytes(secret)
    (other / "results.json").write_text(json.dumps([
        _result("test_secret.py::test_secret", "test_secret", "failed", error="secret"),
    ]), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert ensure_findings_from_results(linked / "run") == []
    assert load_saved_results(linked / "run") == []
    assert not (other / "run").exists()
    assert (other / "failures.json").read_bytes() == secret
    assert (other / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    (real / "results.json").write_text(json.dumps([
        _result("test_home.py::test_home", "test_home", "failed", error="button missing"),
    ]), encoding="utf-8")
    findings = ensure_findings_from_results(real)
    assert findings and findings[0]["nodeid"].endswith("test_home")
    saved = (real / "failures.json").read_bytes()
    assert b"test_home" in saved and secret not in saved
    assert (other / "failures.json").read_bytes() == secret


def test_a_reconciled_result_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.finalization import reconcile

    secret = b"tenant-b-only-reconcile"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    for name in ("results.json", "failures.json", "test_cases.json", "pending_cases.json"):
        (nested / name).write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    row = {"nodeid": "test_home.py::test_home", "test": "test_home", "file": "test_home.py",
           "outcome": "failed", "error": "button missing", "url": "https://shop.test/home"}
    state = {"run_dir": str(linked / "run"), "results": [row], "failures": [], "test_cases": []}
    reconcile(state)
    reconcile({"run_dir": str(linked / "fresh"), "results": [row], "failures": [], "test_cases": []})
    assert not (other / "fresh").exists()
    for name in ("results.json", "failures.json", "test_cases.json", "pending_cases.json", "keep.txt"):
        assert (nested / name).read_bytes() == secret

    real = tmp_path / "real"
    real.mkdir()
    own = reconcile({"run_dir": str(real), "results": [row], "failures": [], "test_cases": []})
    written = (real / "results.json").read_bytes()
    assert b"https://shop.test/home" in written and secret not in written
    assert own["results"][0]["nodeid"] == "test_home.py::test_home"
    assert (nested / "keep.txt").read_bytes() == secret


def test_a_finding_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    import backend.tenancy_store as tenancy
    from backend.agents.executor import _read, _write_run_json
    from backend.finalization import reconcile
    from backend.release_row import record_step
    from backend.report_rebuild import rebuild

    secret = "tenant-b-only-finding"
    other = tmp_path / "other"
    other.mkdir()
    results_text = json.dumps([
        _result("test_home.py::test_secret", "test_secret", "failed", error=secret)])
    failures_text = json.dumps([
        {"id": 0, "nodeid": "test_home.py::test_secret", "error": secret, "source": "test"}])
    jsonl_text = json.dumps(_result("test_home.py::test_secret", "test_secret", "failed", error=secret)) + "\n"
    (other / "results.json").write_text(results_text, encoding="utf-8")
    (other / "failures.json").write_text(failures_text, encoding="utf-8")
    (other / "results.jsonl").write_text(jsonl_text, encoding="utf-8")
    (other / "test_cases.json").write_text(json.dumps([{"title": secret}]), encoding="utf-8")
    (other / "row.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")

    run = tmp_path / "run-a"
    run.mkdir()
    (run / "results.json").symlink_to(other / "results.json")
    (run / "failures.json").symlink_to(other / "failures.json")
    (run / "results.jsonl").symlink_to(other / "results.jsonl")
    (run / "test_cases.json").symlink_to(other / "test_cases.json")
    (run / "row.json").symlink_to(other / "row.json")
    assert load_saved_results(run) == []
    assert secret not in json.dumps(ensure_findings_from_results(run))
    assert _read(run / "results.jsonl") == []
    _write_run_json(run, "results.json", [{"nodeid": "test_home.py::test_ok", "outcome": "passed"}])
    record_step(run, "seed", {"ok": True, "reason": "local"})
    reconciled = reconcile({"run_dir": str(run), "results": [
        _result("test_home.py::test_ok", "test_ok", "failed", error="ours")]})
    assert secret not in json.dumps(reconciled)
    assert (other / "results.json").read_text(encoding="utf-8") == results_text
    assert (other / "failures.json").read_text(encoding="utf-8") == failures_text
    assert (other / "results.jsonl").read_text(encoding="utf-8") == jsonl_text
    assert (other / "row.json").read_text(encoding="utf-8") == json.dumps({"secret": secret})

    linked = tmp_path / "linked-run"
    linked.symlink_to(other, target_is_directory=True)
    try:
        rebuild(linked, tmp_path / "rebuilt")
    except ValueError as exc:
        assert "link" in str(exc)
    else:
        raise AssertionError("rebuild followed a linked run")
    assert not (tmp_path / "rebuilt").exists()

    db = tmp_path / "tenancy.sqlite"
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setenv("QPILOT_TENANT_ID", "t1")
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.index_run(other.name, "t2", source="https://shop.test", verdict="Not Ready", db_path=db)
    try:
        rebuild(other, tmp_path / "rebuilt-tenant")
    except ValueError as exc:
        assert "another tenant" in str(exc)
    else:
        raise AssertionError("rebuild read another tenant")
    assert (other / "failures.json").read_text(encoding="utf-8") == failures_text


def test_a_rebuilt_report_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    from backend.report_rebuild import rebuild

    secret = "tenant-b-only-rebuild"
    other = tmp_path / "other"
    other.mkdir()
    (other / "test_secret.py").write_text(f"# {secret}\n", encoding="utf-8")
    (other / "shot.png").write_bytes(b"tenant-b-only-rebuild")
    (other / "rebuild_comparison.json").write_text(json.dumps({"secret": secret}), encoding="utf-8")

    source = tmp_path / "source"
    tests = source / "generated_tests"
    tests.mkdir(parents=True)
    (tests / "test_keep.py").write_text("def test_keep():\n    assert True\n", encoding="utf-8")
    (tests / "test_secret.py").symlink_to(other / "test_secret.py")
    shots = source / "screenshots"
    shots.mkdir()
    (shots / "01_home.png").symlink_to(other / "shot.png")
    (source / "app_map.json").write_text(json.dumps([
        {"url": "https://shop.test/", "screenshot": "screenshots/01_home.png"}
    ]), encoding="utf-8")
    (source / "results.json").write_text("[]", encoding="utf-8")

    def _summary(state):
        path = Path(state["run_dir"]) / "summary.json"
        path.write_text(json.dumps({
            "metrics": {"single_tests": {"total": 0}, "test_cases": {}, "consistent": True},
            "findings": 0,
        }), encoding="utf-8")
        return {}

    monkeypatch.setattr("backend.agents.reporter.reporter_agent", _summary)
    rebuilt = tmp_path / "rebuilt"
    comparison = rebuild(source, rebuilt)
    copied = (rebuilt / "generated_tests" / "test_keep.py").read_text(encoding="utf-8")
    assert "test_keep" in copied
    assert not (rebuilt / "generated_tests" / "test_secret.py").exists()
    assert secret not in copied
    assert not (rebuilt / "screenshots" / "01_home.png").exists()
    assert (other / "test_secret.py").read_text(encoding="utf-8") == f"# {secret}\n"
    assert (other / "shot.png").read_bytes() == b"tenant-b-only-rebuild"
    assert comparison["source"].endswith("source")

    linked_dest = tmp_path / "linked-dest"
    linked_dest.symlink_to(other, target_is_directory=True)
    try:
        rebuild(source, linked_dest)
    except ValueError as exc:
        assert "link" in str(exc)
    else:
        raise AssertionError("rebuild wrote through a linked folder")
    assert json.loads((other / "rebuild_comparison.json").read_text(encoding="utf-8"))["secret"] == secret


def test_a_pytest_output_file_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.agents.failure_analysis import _gone_items

    secret = "https://other.example/tenant-b-only-gone"
    own = "https://home.example/own-item"
    other = tmp_path / "other"
    other.mkdir()
    output = other / "results_pytest_output.txt"
    output.write_text(f"[data changed] {secret} no longer exists\n", encoding="utf-8")
    before = sorted(p.name for p in other.iterdir())
    run = tmp_path / "run"
    run.mkdir()
    (run / "results_pytest_output.txt").symlink_to(output)
    linked_run = tmp_path / "linked-run"
    linked_run.symlink_to(other, target_is_directory=True)

    assert _gone_items(run) == set()
    assert _gone_items(linked_run) == set()
    assert secret not in _gone_items(run)
    assert output.read_text(encoding="utf-8") == f"[data changed] {secret} no longer exists\n"
    assert sorted(p.name for p in other.iterdir()) == before

    (run / "results_pytest_output.txt").unlink()
    (run / "results_pytest_output.txt").write_text(
        f"[data changed] {own} no longer exists\n", encoding="utf-8")
    found = _gone_items(run)
    assert found == {own}
    assert secret not in found
