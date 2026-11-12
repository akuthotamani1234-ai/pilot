"""The web server's own protection: local-only, header for every change, setup validation, secrets never served.
(No real test run is started here - every request below is refused before that.)"""
import shutil

import pytest
from fastapi.testclient import TestClient

from backend import server

H = {"X-Agentic-QA": "1"}


@pytest.fixture
def client():
    return TestClient(server.app, base_url="http://127.0.0.1:8000")


def test_the_live_list_says_which_test_runs_and_for_how_long(tmp_path):
    """(was: a long test showed only 'running…' for 10 minutes - it looked like a stuck run)"""
    import json
    import time
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


def test_website_check_refuses_metadata_addresses(client):
    r = client.get("/api/check", params={"source": "http://169.254.169.254/"})
    assert r.status_code == 200 and r.json()["ok"] is False and "metadata" in r.json()["error"]
