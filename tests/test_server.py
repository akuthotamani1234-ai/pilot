"""The web server's own protection: local-only, header for every change, setup validation, secrets never served.
(No real test run is started here - every request below is refused before that.)"""
import json
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from backend import server

H = {"X-Agentic-QA": "1"}


@pytest.fixture
def client():
    return TestClient(server.app, base_url="http://127.0.0.1:8000")


@pytest.fixture
def isolated_jobs():
    """Swap the in-memory job table so contract tests never touch a live worker."""
    previous = dict(server.jobs)
    server.jobs.clear()
    try:
        yield server.jobs
    finally:
        server.jobs.clear()
        server.jobs.update(previous)


def test_the_live_list_says_which_test_runs_and_for_how_long(tmp_path):
    """(was: a long test showed only 'running…' for 10 minutes - it looked like a stuck run)"""
    (tmp_path / "test_cases.json").write_text(json.dumps([
        {"id": "journey_1", "title": "Shopping journey", "files": ["test_journeys.py"], "tests": ["test_journey_1"]},
        {"id": "journey_3", "title": "Move through the menu", "files": ["test_journeys.py"], "tests": ["test_journey_3"]}]))
    (tmp_path / "results.jsonl").write_text(json.dumps(
        {"nodeid": "test_journeys.py::test_journey_1", "file": "test_journeys.py", "test": "test_journey_1",
         "outcome": "passed", "checks": 3}) + "\n")
    (tmp_path / "running.results.main.json").write_text(json.dumps(
        {"file": "test_journeys.py", "test": "test_journey_3", "since": time.time() - 155, "limit_s": 180}))
    rows = {r["id"]: r for r in server._case_progress(tmp_path, executing=True)["cases"]}
    assert rows["journey_1"]["status"] == "Passed"
    assert rows["journey_3"]["status"] == "Running" and rows["journey_3"]["detail"].startswith("running for 2:3")
    assert "stops at 3:00" in rows["journey_3"]["detail"]


def test_only_local_host_names_are_answered():
    assert TestClient(server.app, base_url="http://evil.example").get("/api/history").status_code == 400
    assert TestClient(server.app, base_url="http://localhost:8000").get("/api/history").status_code == 200


def test_api_v1_aliases_legacy_routes_and_rejects_unsupported_versions(client):
    legacy = client.get("/api/history")
    v1 = client.get("/api/v1/history")
    assert legacy.status_code == 200 and v1.status_code == 200
    assert v1.json() == legacy.json()
    bad = client.get("/api/v9/history")
    assert bad.status_code == 404 and "not supported" in bad.json()["detail"]
    ready = client.get("/api/v1/enterprise/readiness")
    assert ready.status_code == 200
    body = ready.json()
    assert body["gate_g_complete"] is False and body["gate_i_complete"] is False
    assert body["ops"]["gate_h_complete"] is False
    assert body["blueprint"]["complete"] is False
    assert len(body["blueprint"]["gates"]) == 10
    bp = client.get("/api/v1/blueprint/progress")
    assert bp.status_code == 200 and bp.json()["complete"] is False
    ops = client.get("/api/v1/ops/readiness")
    assert ops.status_code == 200 and ops.json()["gate_h_complete"] is False
    audits = client.get("/api/v1/audit/events")
    assert audits.status_code == 200 and "events" in audits.json()


def test_every_change_needs_the_header(client):
    assert client.post("/api/runs", json={"source": "https://x.test"}).status_code == 403
    assert client.delete("/api/runs/whatever").status_code == 403


@pytest.mark.parametrize("body, message", [
    ({"source": "https://shop.test"}, "permission"),
    ({"source": "https://shop.test", "authorized": True, "environment": "production"}, "PRODUCTION"),
    ({"source": "https://shop.test", "authorized": True, "test_username": "qa"}, "both"),
    ({"source": "https://shop.test", "authorized": True, "login_user_selector": "#u"}, "Login selectors"),
    ({"source": "http://169.254.169.254/latest", "authorized": True}, "metadata"),
    ({"source": "https://admin:pw@shop.test", "authorized": True}, "password"),
    ({"source": "https://shop.test", "authorized": True, "login_url": "https://other.test/login"}, "same website"),
])
def test_setup_problems_get_a_clear_message(client, body, message):
    r = client.post("/api/runs", json=body, headers=H)
    assert r.status_code == 400 and message in r.json()["detail"], r.json()


def test_saved_login_and_hidden_files_are_never_served(client):
    run = server.RUNS / "zz_selftest_20260101_000000"
    (run / ".private").mkdir(parents=True, exist_ok=True)
    try:
        (run / ".private" / "auth.json").write_text('{"cookies": "secret"}')
        (run / "auth.json").write_text('{"cookies": "secret"}')
        (run / "report.html").write_text("<p>ok</p>")
        assert client.get(f"/runs/{run.name}/report.html").status_code == 200
        assert client.get(f"/runs/{run.name}/.private/auth.json").status_code == 404
        assert client.get(f"/runs/{run.name}/auth.json").status_code == 404
    finally:
        shutil.rmtree(run, ignore_errors=True)


def test_sensitive_run_artifacts_are_never_served_even_outside_private(client):
    """APK / contract inputs / android config must 404 even if left at the run root by mistake."""
    run = server.RUNS / "zz_phase11_artifacts_20260101_000000"
    run.mkdir(parents=True, exist_ok=True)
    try:
        (run / "contract_inputs.json").write_text('{"secrets": {"x": "leak-me"}}', encoding="utf-8")
        (run / "android_config.json").write_text('{"apk_path": "/tmp/app.apk"}', encoding="utf-8")
        (run / "app.apk").write_bytes(b"PK\x03\x04fake")
        (run / "active_appium_session.json").write_text('{"session": "s"}', encoding="utf-8")
        (run / "report.html").write_text("<p>ok</p>", encoding="utf-8")
        assert client.get(f"/runs/{run.name}/report.html").status_code == 200
        for name in ("contract_inputs.json", "android_config.json", "app.apk", "active_appium_session.json",
                     "AUTH.JSON"):
            if name == "AUTH.JSON":
                (run / name).write_text("{}", encoding="utf-8")
            r = client.get(f"/runs/{run.name}/{name}")
            assert r.status_code == 404, name
            assert r.json()["detail"] == "not found"
    finally:
        shutil.rmtree(run, ignore_errors=True)


def test_website_check_refuses_metadata_addresses(client):
    r = client.get("/api/check", params={"source": "http://169.254.169.254/"})
    assert r.status_code == 200 and r.json()["ok"] is False and "metadata" in r.json()["error"]


def _assert_detail(response, status, detail):
    assert response.status_code == status, response.text
    body = response.json()
    assert body == {"detail": detail}, body


@pytest.mark.parametrize("path", [
    "/api/report/missing_run_phase8_zzzz",
    "/api/cases/missing_run_phase8_zzzz",
    "/api/pages/missing_run_phase8_zzzz",
    "/api/coverage/missing_run_phase8_zzzz",
    "/api/excel/missing_run_phase8_zzzz",
    "/api/components/missing_run_phase8_zzzz",
    "/api/runs/missing_run_phase8_zzzz/repo-fix",
])
def test_missing_run_ids_return_explicit_not_found(client, path):
    """Missing run folders must keep the stable {detail: run not found} contract."""
    _assert_detail(client.get(path), 404, "run not found")


@pytest.mark.parametrize("path", [
    "/api/report/bad run name",
    "/api/cases/bad run name",
    "/api/pages/bad run name",
])
def test_invalid_run_names_return_explicit_bad_run_name(client, path):
    _assert_detail(client.get(path), 400, "bad run name")


def test_missing_job_ids_return_explicit_not_found(client, isolated_jobs):
    _assert_detail(client.get("/api/runs/999999"), 404, "job not found")
    _assert_detail(client.post("/api/runs/999999/stop", headers=H), 404, "job not found")
    _assert_detail(client.get("/api/runs/999999/review"), 404, "no such test")
    _assert_detail(client.post("/api/runs/999999/review", json={"answers": {}}, headers=H), 404, "no such test")


def test_stop_on_finished_job_says_not_running(client, isolated_jobs):
    isolated_jobs[7] = {
        "id": 7, "source": "https://shop.test", "status": "done", "proc": None, "lines": [],
        "pages": [], "stages": {}, "current": None, "run": None, "started": time.time() - 10,
        "ended": time.time(), "exit_code": 0, "secrets": [],
    }
    _assert_detail(client.post("/api/runs/7/stop", headers=H), 400, "not running")


def test_stopped_and_failed_jobs_report_status_and_exit_code(client, isolated_jobs):
    """UI polling relies on status; exit_code is additive failure detail (None while running)."""
    isolated_jobs[1] = {
        "id": 1, "source": "https://stopped.test", "status": "stopped", "proc": None, "lines": ["stopped"],
        "pages": [], "stages": {"discovery": "done"}, "current": None, "run": None,
        "started": time.time() - 30, "ended": time.time(), "exit_code": 1, "secrets": [],
        "stopping": True,
    }
    isolated_jobs[2] = {
        "id": 2, "source": "https://failed.test", "status": "failed", "proc": None, "lines": ["boom"],
        "pages": [], "stages": {}, "current": None, "run": None,
        "started": time.time() - 20, "ended": time.time(), "exit_code": 2, "secrets": [],
    }
    isolated_jobs[3] = {
        "id": 3, "source": "https://running.test", "status": "running", "proc": None, "lines": [],
        "pages": [], "stages": {"discovery": "running"}, "current": "discovery", "run": None,
        "started": time.time(), "secrets": [],
    }
    stopped = client.get("/api/runs/1").json()
    failed = client.get("/api/runs/2").json()
    running = client.get("/api/runs/3").json()
    assert stopped["status"] == "stopped" and stopped["exit_code"] == 1 and stopped["source"] == "https://stopped.test"
    assert failed["status"] == "failed" and failed["exit_code"] == 2
    assert running["status"] == "running" and running["exit_code"] is None
    # Successful polling shape still carries the fields the chat UI already reads.
    for key in ("id", "source", "status", "run", "stages", "lines", "next", "report_ready", "elapsed"):
        assert key in stopped and key in failed and key in running


def test_execution_failure_shows_up_in_report_and_cases(client):
    """A finished run with setup_error must surface through report/cases without inventing counts."""
    run = server.RUNS / "zz_phase8_fail_20260101_000000"
    run.mkdir(parents=True, exist_ok=True)
    try:
        (run / "summary.json").write_text(json.dumps({
            "source": "https://fail.test", "verdict": "FAIL", "setup_error": "browser would not start",
            "pages": 0, "cases": 0,
        }), encoding="utf-8")
        (run / "test_cases.json").write_text("[]", encoding="utf-8")
        report = client.get(f"/api/report/{run.name}").json()
        cases = client.get(f"/api/cases/{run.name}").json()
        assert report["summary"]["setup_error"] == "browser would not start"
        assert report["run"] == run.name
        assert cases["complete"] is True
        assert cases["empty_reason"] == "browser would not start"
        assert cases["available"] is True and cases["total"] == 0
    finally:
        shutil.rmtree(run, ignore_errors=True)


def test_hidden_run_files_keep_explicit_not_found_detail(client):
    run = server.RUNS / "zz_phase8_secret_20260101_000000"
    (run / ".private").mkdir(parents=True, exist_ok=True)
    try:
        (run / ".private" / "auth.json").write_text('{"cookies": "secret"}', encoding="utf-8")
        r = client.get(f"/runs/{run.name}/.private/auth.json")
        assert r.status_code == 404
        assert r.json()["detail"] == "not found"
    finally:
        shutil.rmtree(run, ignore_errors=True)


class _FakeProcess:
    pid = 4242

    def __init__(self):
        import io
        self.stdout = io.StringIO("")


class _FakeThread:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def test_thorough_run_raises_this_run_budget_env(client, isolated_jobs, monkeypatch):
    """Thorough (or full crawl + repeated controls) must raise per-run budgets without starting a real worker."""
    captured = {}

    def fake_popen(cmd, cwd=None, env=None, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = dict(env or {})
        return _FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(server.threading, "Thread", _FakeThread)
    monkeypatch.setattr(server, "_audit", lambda *a, **k: None)
    monkeypatch.setenv("CRAWL_TIME_LIMIT_MIN", "30")
    monkeypatch.setenv("MAX_TEST_CASES", "300")
    monkeypatch.setenv("PATTERN_SAMPLES", "3")

    response = client.post("/api/runs", headers=H, json={
        "source": "https://shop.example.test", "authorized": True, "thorough": True,
        "max_pages": 0, "llm_provider": "none",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["thorough"] is True
    assert any("Thorough budgets active" in line for line in body["lines"])
    env = captured["env"]
    assert env["QA_THOROUGH"] == "1"
    assert env["EXPLORE_REPEATED_CONTROLS"] == "true"
    assert env["MAX_INTERACTIONS_PER_PAGE"] == "80"
    assert float(env["CRAWL_TIME_LIMIT_MIN"]) >= 60
    assert int(env["MAX_TEST_CASES"]) >= 500
    assert env["PATTERN_SAMPLES"] == "0"
    assert env["SWARM_SAMPLE"] == "0"
    assert "--max-pages" in captured["cmd"] and captured["cmd"][captured["cmd"].index("--max-pages") + 1] == "0"


def test_thorough_does_not_lower_higher_crawl_time_env(client, isolated_jobs, monkeypatch):
    captured = {}

    def fake_popen(cmd, cwd=None, env=None, **kwargs):
        captured["env"] = dict(env or {})
        return _FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(server.threading, "Thread", _FakeThread)
    monkeypatch.setattr(server, "_audit", lambda *a, **k: None)
    monkeypatch.setenv("CRAWL_TIME_LIMIT_MIN", "90")
    monkeypatch.setenv("MAX_TEST_CASES", "800")

    response = client.post("/api/runs", headers=H, json={
        "source": "https://shop.example.test", "authorized": True, "thorough": True,
        "explore_repeated_controls": True, "max_pages": 0, "max_interactions_per_page": 95,
        "llm_provider": "none",
    })
    assert response.status_code == 200, response.text
    env = captured["env"]
    assert env["MAX_INTERACTIONS_PER_PAGE"] == "95"
    assert float(env["CRAWL_TIME_LIMIT_MIN"]) == 90.0
    assert env["MAX_TEST_CASES"] == "800"
    assert env.get("QA_THOROUGH") == "1"


def test_thorough_false_does_not_raise_budgets_even_with_full_crawl(client, isolated_jobs, monkeypatch):
    """Standard intensity / thorough=false must not inherit Thorough floors from explore_repeated + full crawl."""
    captured = {}

    def fake_popen(cmd, cwd=None, env=None, **kwargs):
        captured["env"] = dict(env or {})
        return _FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(server.threading, "Thread", _FakeThread)
    monkeypatch.setattr(server, "_audit", lambda *a, **k: None)
    monkeypatch.setenv("CRAWL_TIME_LIMIT_MIN", "30")
    monkeypatch.setenv("MAX_TEST_CASES", "300")
    monkeypatch.setenv("PATTERN_SAMPLES", "3")

    response = client.post("/api/runs", headers=H, json={
        "source": "https://shop.example.test", "authorized": True, "thorough": False,
        "explore_repeated_controls": True, "max_pages": 0, "max_interactions_per_page": 15,
        "llm_provider": "none",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("thorough") is False
    assert not any("Thorough budgets active" in line for line in body.get("lines") or [])
    env = captured["env"]
    assert env.get("QA_THOROUGH") != "1"
    assert env["EXPLORE_REPEATED_CONTROLS"] == "true"
    assert env["MAX_INTERACTIONS_PER_PAGE"] == "15"
    assert float(env["CRAWL_TIME_LIMIT_MIN"]) == 30.0
    assert env["MAX_TEST_CASES"] == "300"
    assert env["PATTERN_SAMPLES"] == "3"
    assert env["SWARM_SAMPLE"] == "3"


def test_history_lists_incomplete_runs_without_summary(client, tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    incomplete = runs / "zz_incomplete_20260101_000001"
    complete = runs / "zz_complete_20260101_000002"
    incomplete.mkdir(parents=True)
    (incomplete / ".private").mkdir()
    (incomplete / ".private" / "android_config.json").write_text(
        json.dumps({"package_name": "com.example.demo", "app_mode": "installed"}), encoding="utf-8")
    complete.mkdir(parents=True)
    (complete / "summary.json").write_text(
        json.dumps({"source": "https://done.example.test", "verdict": "Ready"}), encoding="utf-8")
    monkeypatch.setattr(server, "RUNS", runs)
    items = client.get("/api/history").json()
    by_run = {item["run"]: item for item in items}
    assert by_run["zz_incomplete_20260101_000001"]["incomplete"] is True
    assert by_run["zz_incomplete_20260101_000001"]["verdict"] == "incomplete"
    assert "com.example.demo" in by_run["zz_incomplete_20260101_000001"]["url"]
    assert by_run["zz_complete_20260101_000002"]["incomplete"] is False
    assert by_run["zz_complete_20260101_000002"]["verdict"] == "Ready"


def test_delete_run_removes_runs_folder(client, tmp_path, monkeypatch, isolated_jobs):
    runs = tmp_path / "runs"
    run = runs / "zz_delete_me_20260101_000003"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(json.dumps({"source": "https://x.test", "verdict": "Ready"}), encoding="utf-8")
    (run / "report.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(server, "RUNS", runs)
    monkeypatch.setattr(server, "_audit", lambda *a, **k: None)
    response = client.delete("/api/runs/zz_delete_me_20260101_000003", headers=H)
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert response.json().get("removed") == "zz_delete_me_20260101_000003"
    assert not run.exists()


def test_home_and_static_are_not_cached_and_show_build_stamp(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "no-store" in (home.headers.get("cache-control") or "").lower()
    assert "build " in home.text
    assert "chat.js?v=" in home.text
    build = client.get("/api/ui-build")
    assert build.status_code == 200
    assert build.json()["build"]
    assert build.json()["assets"]["chat.js"] == build.json()["build"]


def test_a_link_script_is_not_read_through_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-link"
    other = tmp_path / "other"
    suite = other / "runs" / "run" / "generated_tests"
    suite.mkdir(parents=True)
    script = suite / "test_all_links.py"
    script.write_text(f"{{'id': '{secret}'}}\n{{'id': 'other'}}\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    refused = server._case_progress(linked / "runs" / "run", False)
    assert refused["links"]["total"] == 0
    assert secret not in json.dumps(refused)
    assert secret in script.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real" / "generated_tests"
    real.mkdir(parents=True)
    (real / "test_all_links.py").write_text(
        "{'id': 'home-own'}\n{'id': 'home-two'}\n{'id': 'home-three'}\n", encoding="utf-8")
    counted = server._case_progress(real.parent, False)
    assert counted["links"]["total"] == 3
    assert secret not in json.dumps(counted)
    assert secret in script.read_text(encoding="utf-8")


def test_an_automation_check_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.excel import automation_status

    secret = "tenant-b-only-script"
    other = tmp_path / "other"
    suite = other / "runs" / "run" / "generated_tests"
    suite.mkdir(parents=True)
    script = suite / "test_secret.py"
    script.write_text(f"# generated by: {secret}\ndef test_secret():\n    pass\n", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    case = {"id": "secret", "files": ["test_secret.py"], "tests": ["test_secret"]}
    assert automation_status(case, linked / "runs" / "run" / "generated_tests") == ("Pending", "")
    assert secret in script.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "test_home.py").write_text("# generated by: template\ndef test_home():\n    pass\n", encoding="utf-8")
    status, how = automation_status(
        {"id": "home", "files": ["test_home.py"], "tests": ["test_home"]}, real)
    assert (status, how) == ("Automated", "Template")
    assert secret not in f"{status} {how}"
    assert secret in script.read_text(encoding="utf-8")


def test_an_automation_script_name_does_not_follow_a_link_into_another_folder(tmp_path):
    from backend.excel import automation_status

    secret = "tenant-b-only-excel"
    other = tmp_path / "other"
    other.mkdir()
    (other / "test_home.py").write_text(
        f"# generated by: {secret}\ndef test_home():\n    pass\n", encoding="utf-8")
    (other / "keep.txt").write_text(secret, encoding="utf-8")
    tests = tmp_path / "generated_tests"
    tests.mkdir()
    (tests / "linked").symlink_to(other, target_is_directory=True)
    status, how = automation_status(
        {"id": "home", "files": ["linked/test_home.py"], "tests": ["test_home"]}, tests)
    assert (status, how) == ("Not automated", "")
    assert secret not in f"{status} {how}"
    assert (other / "test_home.py").read_text(encoding="utf-8").count(secret) == 1
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "test_home.py").write_text("# generated by: template\ndef test_home():\n    pass\n", encoding="utf-8")
    status, how = automation_status(
        {"id": "home", "files": ["test_home.py"], "tests": ["test_home"]}, real)
    assert (status, how) == ("Automated", "Template")
    assert secret not in f"{status} {how}"
    assert (other / "test_home.py").read_text(encoding="utf-8").count(secret) == 1


def test_a_contract_status_does_not_follow_a_link_into_another_folder(tmp_path):
    import json

    from backend.excel import automation_status

    secret = "tenant-b-only-contract"
    other = tmp_path / "other"
    other.mkdir()
    secret_text = json.dumps({"id": secret})
    (other / "qa_contracts.json").write_text(secret_text, encoding="utf-8")
    (other / "keep.txt").write_text(secret, encoding="utf-8")
    run = tmp_path / "run"
    tests = run / "generated_tests"
    tests.mkdir(parents=True)
    (run / "qa_contracts.json").symlink_to(other / "qa_contracts.json")
    case = {"id": "contract_home", "kind": "contract", "files": [], "tests": ["test_contract_home"]}
    status, how = automation_status(case, tests)
    assert status != "Automated"
    assert secret not in f"{status} {how}"
    assert (other / "qa_contracts.json").read_text(encoding="utf-8") == secret_text
    assert not (other / "fresh").exists()
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret

    (run / "qa_contracts.json").unlink()
    (run / "qa_contracts.json").write_text(json.dumps({"id": "home-own"}), encoding="utf-8")
    status, how = automation_status(case, tests)
    assert (status, how) == ("Automated", "Trusted QA contract runtime")
    assert secret not in f"{status} {how}"
    assert (other / "qa_contracts.json").read_text(encoding="utf-8") == secret_text
    assert (other / "keep.txt").read_text(encoding="utf-8") == secret


def test_a_coverage_sheet_does_not_follow_a_link_into_another_folder(tmp_path):
    from openpyxl import Workbook

    from backend.excel import _coverage_sheet

    secret = "tenant-b-only-control"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    coverage = nested / "coverage.json"
    coverage.write_text(json.dumps({
        "tested": 1, "total": 1,
        "pages": [{"url": "https://other.test/", "items": [{
            "status": "tested", "name": secret, "kind": "button", "reason": secret, "selector": "#secret",
        }]}],
    }), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    refused = Workbook()
    _coverage_sheet(refused, linked / "runs" / "run")
    assert "Coverage" not in refused.sheetnames
    assert secret in coverage.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "coverage.json").write_text(json.dumps({
        "tested": 1, "total": 1,
        "pages": [{"url": "https://home.test/", "items": [{
            "status": "tested", "name": "home-own", "kind": "button", "reason": "", "selector": "#home",
        }]}],
    }), encoding="utf-8")
    book = Workbook()
    _coverage_sheet(book, real)
    text = " ".join(str(cell.value) for row in book["Coverage"].iter_rows() for cell in row if cell.value)
    assert "home-own" in text
    assert secret not in text
    assert secret in coverage.read_text(encoding="utf-8")


def test_a_feature_sheet_does_not_follow_a_link_into_another_folder(tmp_path):
    from openpyxl import Workbook

    from backend.excel import _registry_sheet

    secret = "tenant-b-only-feature"
    other = tmp_path / "other"
    nested = other / "runs" / "run"
    nested.mkdir(parents=True)
    registry = nested / "registry.json"
    registry.write_text(json.dumps({"features": {"f1": {
        "id": "f1", "level": "control", "kind": "button", "name": secret,
        "pages": ["https://other.test/"], "status": "verified", "tests": [],
    }}}), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    refused = Workbook()
    _registry_sheet(refused, linked / "runs" / "run")
    assert "Features" not in refused.sheetnames
    assert secret in registry.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    (real / "registry.json").write_text(json.dumps({"features": {"f1": {
        "id": "home", "level": "control", "kind": "button", "name": "home-own",
        "pages": ["https://home.test/"], "status": "verified", "tests": [],
    }}}), encoding="utf-8")
    book = Workbook()
    _registry_sheet(book, real)
    text = " ".join(str(cell.value) for row in book["Features"].iter_rows() for cell in row if cell.value)
    assert "home-own" in text
    assert secret not in text
    assert secret in registry.read_text(encoding="utf-8")


def test_a_schedule_file_is_not_read_through_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-schedule"
    other = tmp_path / "other"
    nested = other / "app"
    nested.mkdir(parents=True)
    saved = nested / "schedules.json"
    saved.write_text(json.dumps([{"url": secret, "every": "daily"}]), encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(server, "SCHEDULES", linked / "app" / "schedules.json")
    assert server._schedules() == []
    assert server._save_schedules([{"url": "https://ours.test"}]) is False
    assert secret in saved.read_text(encoding="utf-8")
    assert not (other / "fresh").exists()

    real = tmp_path / "real"
    real.mkdir()
    own = real / "schedules.json"
    own.write_text(json.dumps([{"url": "https://home.test", "every": "daily"}]), encoding="utf-8")
    monkeypatch.setattr(server, "SCHEDULES", own)
    assert server._schedules()[0]["url"] == "https://home.test"
    assert server._save_schedules([{"url": "https://home-own.test"}]) is True
    assert json.loads(own.read_text(encoding="utf-8"))[0]["url"] == "https://home-own.test"
    assert secret not in own.read_text(encoding="utf-8")
    assert secret in saved.read_text(encoding="utf-8")
