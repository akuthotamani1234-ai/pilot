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
