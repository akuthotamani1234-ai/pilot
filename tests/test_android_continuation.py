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


def test_an_android_test_run_does_not_follow_a_link_into_another_run(tmp_path, monkeypatch):
    import pytest

    from backend.qa_runtime import private_inputs

    secret = "tenant-b-only-exec"
    other = tmp_path / "other"
    other.mkdir()
    (other / "auto_secrets.json").write_text(json.dumps({"password": secret}), encoding="utf-8")
    (other / "contract_inputs.json").write_text(json.dumps({"secrets": {"password": secret}}), encoding="utf-8")
    (other / "active_appium_session.json").write_text(json.dumps({"session_id": secret}), encoding="utf-8")
    (other / "test_android_generated.py").write_text(f"# {secret}\n", encoding="utf-8")

    run = tmp_path / "run"
    run.mkdir()
    (run / ".private").symlink_to(other, target_is_directory=True)
    tests = run / "generated_tests"
    tests.mkdir()
    (tests / "test_android_generated.py").symlink_to(other / "test_android_generated.py")
    monkeypatch.setattr(android_pipeline, "_run_mobile_process", lambda *a, **k: pytest.fail("started"))
    with pytest.raises(android_pipeline.AndroidEnvironmentError, match="link"):
        android_pipeline._execute_mobile({"run_dir": str(run), "config": {}, "test_cases": [{"id": "new"}]})
    assert json.loads((other / "auto_secrets.json").read_text(encoding="utf-8"))["password"] == secret
    assert json.loads((other / "contract_inputs.json").read_text(encoding="utf-8"))["secrets"]["password"] == secret
    assert json.loads((other / "active_appium_session.json").read_text(encoding="utf-8"))["session_id"] == secret
    assert (other / "test_android_generated.py").read_text(encoding="utf-8") == f"# {secret}\n"
    assert private_inputs(run) == {"secrets": {}, "databases": {}}
    assert android_pipeline._cleanup_worker_session(run, {"appium_url": "http://127.0.0.1:4723"}) == ""
    assert json.loads((other / "active_appium_session.json").read_text(encoding="utf-8"))["session_id"] == secret


def test_an_android_session_file_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-session"
    other = tmp_path / "other"
    private = other / "runs" / "run" / ".private"
    private.mkdir(parents=True)
    session = private / "active_appium_session.json"
    session.write_text(json.dumps({"session_id": secret}), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    calls = []

    class Client:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def delete(self, url, **kwargs):
            calls.append(url)
            return type("Response", (), {"status_code": 200})()

    monkeypatch.setattr(android_pipeline.requests, "Session", Client)
    assert android_pipeline._cleanup_worker_session(
        linked / "runs" / "run", {"appium_url": "http://127.0.0.1:4723"}) == ""
    assert calls == []
    assert json.loads(session.read_text(encoding="utf-8"))["session_id"] == secret
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    own = real / ".private"
    own.mkdir(parents=True)
    evidence = own / "active_appium_session.json"
    evidence.write_text(json.dumps({"session_id": "home-own"}), encoding="utf-8")
    assert android_pipeline._cleanup_worker_session(real, {"appium_url": "http://127.0.0.1:4723"}) == ""
    assert calls == ["http://127.0.0.1:4723/session/home-own"]
    assert not evidence.exists()
    assert json.loads(session.read_text(encoding="utf-8"))["session_id"] == secret


def test_contract_inputs_do_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    from backend.qa_runtime import private_inputs

    monkeypatch.delenv("ANDROID_CONTRACT_INPUTS", raising=False)
    secret = "tenant-b-only-contract"
    other = tmp_path / "other"
    nested = other / "runs" / "run" / ".private"
    nested.mkdir(parents=True)
    (nested / "contract_inputs.json").write_text(
        json.dumps({"secrets": {"password": secret}, "databases": {}}), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    assert private_inputs(linked / "runs" / "run") == {"secrets": {}, "databases": {}}
    assert json.loads((nested / "contract_inputs.json").read_text(encoding="utf-8"))["secrets"]["password"] == secret
    assert not (other / "fresh").exists()

    real = tmp_path / "real" / ".private"
    real.mkdir(parents=True)
    (real / "contract_inputs.json").write_text(
        json.dumps({"secrets": {"password": "home-own"}, "databases": {"shop": "home.sqlite"}}),
        encoding="utf-8")
    loaded = private_inputs(tmp_path / "real")
    assert loaded["secrets"]["password"] == "home-own"
    assert loaded["databases"]["shop"] == "home.sqlite"
    assert secret not in json.dumps(loaded)
    assert json.loads((nested / "contract_inputs.json").read_text(encoding="utf-8"))["secrets"]["password"] == secret


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
