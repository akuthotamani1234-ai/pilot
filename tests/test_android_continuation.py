"""Exercise worker selection and the real resume API without an Appium session."""
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend import android_pipeline, server
from tests.test_android_workspace import case, journal, save


def test_execution_keeps_completed_results_and_selects_only_pending_cases(tmp_path, monkeypatch):
    cases = [case("passed"), case("failed"), case("uncertain"), case("new")]
    script = tmp_path / "generated_tests/test_android_generated.py"
    script.parent.mkdir()
    script.write_text("# validated fixture", encoding="utf-8")
    journal(tmp_path, "android_results.jsonl", [{"id": "passed", "outcome": "passed", "checks": 1},
                                              {"id": "failed", "outcome": "failed", "checks": 1}])
    journal(tmp_path, "android_attempts.jsonl", [{"id": "uncertain"}])
    monkeypatch.setattr(android_pipeline, "validate_mobile_script", lambda *args: None)
    monkeypatch.setattr(android_pipeline, "_cleanup_worker_session", lambda *args: "")
    launched = []
    def execute(command, env, timeout):
        launched.extend(json.loads(env["ANDROID_PENDING_CASES"]))
        assert "passed" in (tmp_path / "android_results.jsonl").read_text(encoding="utf-8")
        with (tmp_path / "android_results.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"id": "new", "outcome": "passed", "checks": 1}) + "\n")
        return SimpleNamespace(stdout="", stderr="", returncode=0), False
    monkeypatch.setattr(android_pipeline, "_run_mobile_process", execute)
    state = {"run_dir": str(tmp_path), "config": {}, "test_cases": cases}
    result = android_pipeline._execute_mobile(state)
    outcomes = {row["id"]: row["outcome"] for row in result["results"]}
    assert launched == ["new"]
    assert outcomes == {"passed": "passed", "failed": "failed", "uncertain": "blocked", "new": "passed"}
    again = android_pipeline._execute_mobile(state)
    assert launched == ["new"]  # every pending case is now terminal
    assert {row["id"]: row["outcome"] for row in again["results"]} == outcomes


def test_resume_api_does_not_start_a_worker_when_every_case_completed(tmp_path, monkeypatch):
    root = tmp_path / "android_done"
    root.mkdir()
    save(root, ".private/android_config.json", {})
    save(root, "test_cases.json", [case("completed")])
    journal(root, "android_results.jsonl", [{"id": "completed", "outcome": "failed"}])
    monkeypatch.setattr(server, "RUNS", tmp_path)
    response = TestClient(server.app, base_url="http://127.0.0.1:8000").post(
        '/api/android/runs/android_done/resume', headers={"X-Agentic-QA": "1"})
    assert response.status_code == 409
    assert "safely resumable" in response.json()["detail"]


def test_android_coverage_api_returns_reasons_without_private_files(tmp_path, monkeypatch):
    root = tmp_path / "android_read"
    root.mkdir()
    save(root, ".private/android_config.json", {"private_marker": "never-publish-this"})
    save(root, "test_cases.json", [{**case("missing"), "blocked": True, "automation_note": "Missing test account"}])
    monkeypatch.setattr(server, "RUNS", tmp_path)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    response = client.get('/api/android/runs/android_read/coverage')
    assert response.status_code == 200
    assert response.json()["cases"][0]["reason"] == "Missing test account"
    assert "never-publish-this" not in response.text
    assert client.get('/api/android/runs/..%5Coutside/coverage').status_code != 200
