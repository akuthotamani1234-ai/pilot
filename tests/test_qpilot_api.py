"""Public Qpilot APIs expose durable progress and require a concrete reviewed proposal."""
import json

import pytest
from fastapi.testclient import TestClient

from backend import server


@pytest.fixture
def api(tmp_path, monkeypatch):
    root = tmp_path / "fixture-run"
    root.mkdir()
    monkeypatch.setattr(server, "RUNS", tmp_path)
    monkeypatch.setattr(server, "jobs", {7: {"run": root.name}, 8: {"run": None}})
    return TestClient(server.app, base_url="http://127.0.0.1"), root


def test_event_api_recovers_cursor_and_validates_bounds(api):
    client, root = api
    (root / "events.fixture.main.jsonl").write_text(json.dumps({"id": "one", "text": "Open form"}) + "\n", encoding="utf-8")
    first = client.get("/api/runs/7/events").json()
    assert first["events"][0]["id"] == "one"
    assert client.get("/api/runs/7/events", params={"after": first["cursor"]}).json()["events"] == []
    assert client.get("/api/runs/7/events?after=bad!").status_code == 400
    assert client.get("/api/runs/7/events?limit=501").status_code == 422
    assert client.get("/api/runs/99/events").status_code == 404
    assert client.get("/api/runs/8/events").json()["events"] == []


def test_repository_panel_exists_without_code_suggestions(api):
    client, root = api
    result = client.get(f"/api/runs/{root.name}/repo-fix")
    assert result.status_code == 200
    assert result.json()["candidates"] == []
    assert result.json()["preparation"]["status"] == "idle"


def test_publication_without_review_is_rejected_before_github(api, monkeypatch):
    from backend import repo_fix
    client, root = api
    monkeypatch.setattr(repo_fix, "create_pr", lambda *a, **k: pytest.fail("An unreviewed request must not publish"))
    path = f"/api/runs/{root.name}/repo-fix/create"
    assert client.post(path, json={}).status_code == 403
    rejected = client.post(path, json={}, headers={"X-Agentic-QA": "1"})
    assert rejected.status_code == 400
    assert "review" in rejected.json()["detail"]


def test_watch_and_fast_modes_normalize_legacy_browser_flag():
    for mode, visible in [("watch", True), ("fast", False)]:
        request = server.RunRequest(source="https://fixture.test", authorized=True, execution_mode=mode,
                                    show_browser=not visible, llm_provider="none")
        server._validate(request, request.source)
        assert request.show_browser is visible
