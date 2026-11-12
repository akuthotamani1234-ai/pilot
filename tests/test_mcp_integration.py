"""Prepared MCP regression checks. No browser, device, network service or LLM is needed."""
import json
from pathlib import Path

import pytest

from backend.mcp_bridge import BlowAIBridge, BridgeError, _bounded, local_url, require_permission, run_name, website_url


@pytest.mark.parametrize("value", [
    "https://example.com:8000", "http://127.0.0.1.evil.test", "http://localhost@evil.test",
    "http://user:password@127.0.0.1:8000", "file:///C:/tmp", "http://127.0.0.1:8000/api",
    "http://127.0.0.1:8000?redirect=evil", "http://localhost:99999", "http://localhost:8000#x",
])
def test_bridge_refuses_non_loopback_origins(value):
    with pytest.raises(BridgeError):
        local_url(value)


@pytest.mark.parametrize("value", ["..", ".", ".private", "../secret", r"..\secret", "a/b", "a%2fb", ""])
def test_run_artifacts_cannot_select_paths(value):
    with pytest.raises(BridgeError):
        run_name(value)


def test_plain_run_id_and_loopback_origin_are_supported():
    assert run_name("example.test_20261106_001200") == "example.test_20261106_001200"
    assert local_url("http://127.0.0.1:8100/") == "http://127.0.0.1:8100"
    assert local_url("http://[::1]:8000") == "http://[::1]:8000"


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_start_requires_explicit_boolean_authorization(value):
    with pytest.raises(BridgeError):
        require_permission(value)


def test_embedded_url_credentials_are_rejected():
    with pytest.raises(BridgeError):
        website_url("https://username:password@example.test/")


def test_bounded_evidence_discloses_omitted_details(monkeypatch):
    monkeypatch.setenv("BLOWAI_SECRET_MCP_CHECK", "do-not-expose-this-secret")
    result = _bounded({"message": "do-not-expose-this-secret", "items": list(range(150)), "long": "x" * 4000})
    assert "do-not-expose-this-secret" not in json.dumps(result)
    assert result["details_truncated"] is True
    assert len(result["data"]["items"]) == 100
    assert "untrusted" in result["content_notice"]


def test_api_identity_is_checked_before_any_start(monkeypatch):
    bridge = BlowAIBridge()
    calls = []

    def fake_send(method, route, **kwargs):
        calls.append((method, route))
        return {"product": "another-server", "bridge_version": 1}
    monkeypatch.setattr(bridge, "_send", fake_send)
    with pytest.raises(BridgeError):
        bridge.post("/api/runs", {"authorized": True})
    assert calls == [("GET", "/api/mcp/info")]


def test_missing_ui_error_does_not_retry_post(monkeypatch):
    import requests
    bridge = BlowAIBridge()
    calls = []

    def fail_request(self, method, *args, **kwargs):
        calls.append(method)
        raise requests.Timeout("local timeout")
    monkeypatch.setattr(requests.Session, "request", fail_request)
    with pytest.raises(BridgeError, match="list_runs before retrying"):
        bridge._send("POST", "/api/runs", body={"authorized": True})
    assert calls == ["POST"]


def test_stdio_tools_register_without_contacting_ui(monkeypatch):
    pytest.importorskip("mcp.server")
    from backend.mcp_server import build_server
    monkeypatch.setattr(BlowAIBridge, "_send", lambda *a, **k: pytest.fail("Registration must not contact UI"))
    server = build_server()
    tools = {t.name: t for t in server._tool_manager.list_tools()}
    assert len(tools) == 11
    for name in ("crawl_website", "start_web_test", "start_android_test"):
        tool = tools[name]
        assert tool.parameters["properties"]["authorized"]["default"] is False
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is True
    assert tools["get_run_status"].annotations.read_only_hint is True
    assert tools["stop_run"].parameters["properties"]["confirmed"]["default"] is False


def test_discovery_report_does_not_fabricate_test_passes(tmp_path):
    from backend.discovery_report import discovery_report
    result = discovery_report({"run_id": "inventory", "run_dir": str(tmp_path), "url": "https://example.test",
                              "discovery_only": True,
                              "app_map": [{"url": "https://example.test", "title": "<script>bad</script>", "status": 200}]})
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["tests"] == summary["passed"] == 0
    assert result["verdict"] == "Insufficient Evidence"
    assert summary["discovery_finished"] is True
    assert not (tmp_path / "baseline.json").exists()
    assert "<script>bad</script>" not in (tmp_path / "report.html").read_text(encoding="utf-8")


def test_discovery_graph_has_no_test_baseline_or_integration_nodes():
    from backend.graph import build_graph
    graph = build_graph(discovery_only=True).get_graph()
    assert set(graph.nodes) == {"__start__", "setup", "discovery", "report", "__end__"}


def test_mcp_views_paginate_logs_and_refuse_private_sections(tmp_path):
    import threading

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.mcp_api import register_mcp_api

    report_dir = tmp_path / "run"
    report_dir.mkdir()
    (report_dir / "results.json").write_text(json.dumps([{"id": n} for n in range(5)]), encoding="utf-8")
    app = FastAPI()
    jobs = {1: {"id": 1, "status": "running", "lines": ["a", "b", "c"], "pages": []}}
    def read_json(path, default):
        return json.loads(path.read_text()) if path.exists() else default
    register_mcp_api(app, jobs, threading.Lock(), lambda run: report_dir, read_json)
    with TestClient(app) as client:
        response = client.get("/api/mcp/jobs/1?since=1&limit=1").json()
        assert response["lines"] == ["b"] and response["next"] == 2
        result = client.get("/api/mcp/reports/run?section=results&offset=2&limit=2").json()
        assert result["items"] == [{"id": 2}, {"id": 3}]
        assert result["total"] == 5
        assert client.get("/api/mcp/reports/run?section=.private").status_code == 400
        assert client.get("/api/mcp/jobs/1?since=-1").status_code == 400
        assert client.get("/api/mcp/reports/run?section=summary").json()["available"] is False


def test_generated_client_paths_are_absolute_and_no_credentials_are_embedded(tmp_path):
    from setup.mcp_config import configuration
    config = configuration(tmp_path)["mcpServers"]["blow-ai"]
    assert Path(config["command"]).is_absolute()
    assert Path(config["args"][-1]).is_absolute()
    assert config["env"] == {"BLOWAI_UI_URL": "http://127.0.0.1:8000"}
