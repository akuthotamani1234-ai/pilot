"""Every agent of a run is registered at the start and shows only states the run really reached."""
import pytest
from fastapi.testclient import TestClient

from backend import agent_registry, server
from backend.graph import _traced


def test_stages_register_at_start_and_report_real_states(tmp_path):
    order = ("setup", "discovery", "test_design", "report")
    state = {"run_dir": str(tmp_path)}
    _traced("setup", lambda s: {}, order)(state)
    snap = {a["stage"]: a for a in agent_registry.snapshot(tmp_path)["agents"]}
    assert list(snap) == list(order)
    assert snap["setup"]["status"] == "completed"
    assert snap["discovery"]["status"] == "waiting" and snap["discovery"]["depends_on"] == ["setup"]
    _traced("discovery", lambda s: {"app_map": [{"auth": True}, {"auth": False}]}, order)(state)
    snap = {a["stage"]: a for a in agent_registry.snapshot(tmp_path)["agents"]}
    assert snap["discovery"]["status"] == "completed"
    assert snap["discovery"]["detail"] == "2 page(s), 1 behind the login"
    assert snap["discovery"]["started"] <= snap["discovery"]["finished"]
    agent_registry.finish(tmp_path)  # test_design and report never ran
    snap = {a["stage"]: a for a in agent_registry.snapshot(tmp_path)["agents"]}
    assert snap["test_design"]["status"] == "skipped" and snap["report"]["status"] == "skipped"


def test_a_failing_agent_is_recorded_as_failed(tmp_path):
    def broken(_state):
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        _traced("discovery", broken, ("setup", "discovery"))({"run_dir": str(tmp_path)})
    snap = {a["stage"]: a for a in agent_registry.snapshot(tmp_path)["agents"]}
    assert snap["discovery"]["status"] == "failed" and snap["discovery"]["detail"] == "stopped"
    assert snap["setup"]["status"] == "waiting"


def test_agents_api_serves_the_registry(tmp_path, monkeypatch):
    root = tmp_path / "run1"
    root.mkdir()
    agent_registry.register(root, ["setup", "discovery"])
    monkeypatch.setattr(server, "RUNS", tmp_path)
    monkeypatch.setattr(server, "jobs", {3: {"run": root.name}, 4: {"run": None}})
    client = TestClient(server.app, base_url="http://127.0.0.1")
    body = client.get("/api/runs/3/agents").json()
    assert [a["stage"] for a in body["agents"]] == ["setup", "discovery"]
    assert client.get("/api/runs/4/agents").json() == {"agents": []}
    assert client.get("/api/runs/99/agents").status_code == 404
