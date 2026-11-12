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
    with pytest.raises(BridgeError, match=r"timed out|list_runs before retrying"):
        bridge._send("POST", "/api/runs", body={"authorized": True})
    assert calls == ["POST"]


def test_disabled_mcp_access_message_names_privacy_mode(monkeypatch):
    bridge = BlowAIBridge()
    monkeypatch.setattr(bridge, "verify", lambda: {
        "product": "blow-ai", "bridge_version": 1,
        "privacy": {"mcp_allowed": False, "mode": "local", "allow_mcp": False},
    })
    with pytest.raises(BridgeError, match=r"MCP data access is disabled.*local"):
        bridge.get("/api/history")


@pytest.mark.parametrize("status,detail,needle", [
    (400, "Use a nonnegative offset", r"Invalid MCP request \(HTTP 400\)"),
    (403, "MCP data access is disabled. Approve your assistant in Privacy settings.",
     r"MCP data access is disabled"),
    (404, "Job not found", r"Not found \(HTTP 404\)"),
    (413, "too large for MCP", r"too large for MCP \(HTTP 413\)"),
])
def test_http_error_mapping_is_actionable_and_redacts_secrets(status, detail, needle, monkeypatch):
    import requests
    bridge = BlowAIBridge()
    monkeypatch.setenv("BLOWAI_SECRET_MCP_ERR", "super-secret-mcp-token")

    class FakeResponse:
        status_code = status
        ok = False

        def iter_content(self, _size):
            payload = json.dumps({"detail": f"{detail} super-secret-mcp-token"}).encode()
            yield payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_request(self, method, url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(requests.Session, "request", fake_request)
    with pytest.raises(BridgeError, match=needle) as err:
        bridge._send("GET", "/api/mcp/jobs/1")
    assert "super-secret-mcp-token" not in str(err.value)


def test_permission_helper_rejects_truthy_non_true_values():
    with pytest.raises(BridgeError, match="Permission required"):
        require_permission("yes")
    require_permission(True)  # exact True is the only accepted authorization


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
    for name in ("crawl_website", "start_web_test"):
        props = tools[name].parameters["properties"]
        assert props["max_pages"]["default"] == 0
        assert props["max_depth"]["default"] == 12
        assert props["max_pages"]["minimum"] == 0
    assert tools["get_run_status"].annotations.read_only_hint is True
    assert tools["stop_run"].parameters["properties"]["confirmed"]["default"] is False


def test_mcp_web_start_posts_thorough_budgets(monkeypatch):
    """crawl_website / start_web_test must post Thorough-aligned RunRequest fields via the bridge."""
    import asyncio

    pytest.importorskip("mcp.server")
    from backend.mcp_server import THOROUGH_INTERACTIONS, build_server

    posts = []

    def fake_send(self, method, route, **kwargs):
        if method == "GET" and route == "/api/mcp/info":
            return {"product": "blow-ai", "bridge_version": 1,
                    "privacy": {"mcp_allowed": True, "mode": "local", "allow_mcp": True}}
        if method == "POST" and route == "/api/runs":
            posts.append(kwargs.get("body") or {})
            return {"id": len(posts), "status": "running"}
        raise AssertionError(f"unexpected {method} {route}")

    monkeypatch.setattr(BlowAIBridge, "_send", fake_send)
    server = build_server()

    async def call_starts():
        await server.call_tool("crawl_website", {"url": "https://example.test", "authorized": True})
        await server.call_tool("start_web_test", {
            "url": "https://example.test", "authorized": True, "llm_provider": "none",
        })

    asyncio.run(call_starts())
    assert len(posts) == 2
    for body in posts:
        assert body["thorough"] is True
        assert body["explore_repeated_controls"] is True
        assert body["max_interactions_per_page"] == THOROUGH_INTERACTIONS
        assert body["max_pages"] == 0
        assert body["max_depth"] == 12
        assert body["authorized"] is True
        assert body["website_only"] is True


def test_bridge_error_surfaces_as_tool_error_not_unexpected(monkeypatch):
    """BridgeError must reach the MCP client as ToolError text, not UnexpectedToolError."""
    import asyncio

    pytest.importorskip("mcp.server")
    from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

    from backend.mcp_server import build_server

    monkeypatch.setattr(BlowAIBridge, "_send", lambda *a, **k: pytest.fail("Permission denial must not contact UI"))
    server = build_server()

    async def call_denied_tools():
        with pytest.raises(ToolError, match=r"Permission required") as web_err:
            await server.call_tool("start_web_test", {"url": "https://example.test", "authorized": False})
        assert not isinstance(web_err.value, UnexpectedToolError)
        assert "authorized=true" in str(web_err.value)

        with pytest.raises(ToolError, match=r"Stopping interrupts a run") as stop_err:
            await server.call_tool("stop_run", {"job_id": 1, "confirmed": False})
        assert not isinstance(stop_err.value, UnexpectedToolError)
        assert "confirmed=true" in str(stop_err.value)

    asyncio.run(call_denied_tools())


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
    (report_dir / "failures.json").write_text("{not-json", encoding="utf-8")
    app = FastAPI()
    jobs = {1: {"id": 1, "status": "running", "lines": ["a", "b", "c"], "pages": []}}
    def read_json(path, default):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return default
    register_mcp_api(app, jobs, threading.Lock(), lambda run: report_dir, read_json)
    with TestClient(app) as client:
        response = client.get("/api/mcp/jobs/1?since=1&limit=1").json()
        assert response["lines"] == ["b"] and response["next"] == 2
        result = client.get("/api/mcp/reports/run?section=results&offset=2&limit=2").json()
        assert result["items"] == [{"id": 2}, {"id": 3}]
        assert result["total"] == 5
        assert client.get("/api/mcp/reports/run?section=.private").status_code == 400
        assert client.get("/api/mcp/jobs/1?since=-1").status_code == 400
        assert "Invalid request" in client.get("/api/mcp/jobs/1?since=-1").json()["detail"]
        assert client.get("/api/mcp/reports/run?section=summary").json()["available"] is False
        corrupt = client.get("/api/mcp/reports/run?section=failures")
        assert corrupt.status_code == 422
        assert "could not be read as JSON" in corrupt.json()["detail"]


def test_generated_client_paths_are_absolute_and_no_credentials_are_embedded(tmp_path):
    from setup.mcp_config import configuration
    config = configuration(tmp_path)["mcpServers"]["blow-ai"]
    assert Path(config["command"]).is_absolute()
    assert Path(config["args"][-1]).is_absolute()
    assert config["env"] == {"BLOWAI_UI_URL": "http://127.0.0.1:8000"}
