"""Privacy regressions prepared for the later verification stage. No real models/devices are needed."""
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import privacy
from backend.privacy_api import MCPPresence, register_privacy_api


@pytest.fixture
def policy_file(tmp_path, monkeypatch):
    path = tmp_path / "private" / "privacy.json"
    monkeypatch.setattr(privacy, "POLICY_PATH", path)
    monkeypatch.delenv("BLOWAI_PRIVACY_MODE", raising=False)
    return path


def test_missing_or_corrupt_preferences_fail_closed(policy_file):
    assert privacy.public_policy()["mode"] == "local"
    assert privacy.public_policy()["mcp_allowed"] is False
    policy_file.parent.mkdir()
    policy_file.write_text('{"mode":"cloud","cloud_consent":false}', encoding="utf-8")
    assert privacy.public_policy()["allowed_providers"] == ["none", "ollama"]


def test_cloud_and_local_assistant_need_separate_explicit_consent(policy_file):
    with pytest.raises(ValidationError):
        privacy.PrivacyPolicy(mode="cloud")
    with pytest.raises(ValidationError):
        privacy.PrivacyPolicy(allow_mcp=True)
    local = privacy.PrivacyPolicy(allow_mcp=True, local_assistant_confirmed=True)
    privacy.save_policy(local)
    assert privacy.load_policy().allow_mcp is True


def test_saved_cloud_model_is_not_silently_used_in_local_mode(policy_file):
    assert privacy.select_provider(None, "openai", "http://localhost:11434") == "none"
    with pytest.raises(privacy.PrivacyError, match="Cloud AI is disabled"):
        privacy.select_provider("openai", "ollama", "http://localhost:11434")
    with pytest.raises(privacy.PrivacyError, match="loopback"):
        privacy.select_provider("ollama", "ollama", "http://external-model.test:11434")


def test_stale_privacy_choice_is_rejected(policy_file):
    with pytest.raises(privacy.PrivacyError, match="changed"):
        privacy.select_provider("none", "none", "http://localhost:11434", expected_mode="cloud")


def test_worker_cannot_restore_cloud_credentials_from_dotenv(policy_file, tmp_path, monkeypatch):
    from backend.config import _load_dotenv
    env = {"LLM_PROVIDER": "none", "OPENAI_API_KEY": "fixture-key", "SLACK_WEBHOOK_URL": "fixture-webhook",
           "JIRA_API_TOKEN": "fixture-jira"}
    snapshot = privacy.apply_worker_policy(env)
    assert snapshot["mode"] == "local"
    assert env["BLOWAI_PRIVACY_MODE"] == "local"
    for key in ("OPENAI_API_KEY", "SLACK_WEBHOOK_URL", "JIRA_API_TOKEN"):
        assert env[key] == ""
        monkeypatch.setenv(key, env[key])
    dotenv = tmp_path / "fixture.env"
    dotenv.write_text("OPENAI_API_KEY=must-not-restore\nSLACK_WEBHOOK_URL=must-not-restore\n", encoding="utf-8")
    _load_dotenv(dotenv)
    import os
    assert os.environ["OPENAI_API_KEY"] == os.environ["SLACK_WEBHOOK_URL"] == ""


def test_local_worker_stays_local_after_workspace_cloud_opt_in(policy_file, monkeypatch):
    privacy.save_policy(privacy.PrivacyPolicy(mode="cloud", cloud_consent=True))
    monkeypatch.setenv("BLOWAI_PRIVACY_MODE", "local")
    assert privacy.runtime_mode() == "local"
    with pytest.raises(privacy.PrivacyError):
        privacy.guard_provider("openai", "http://localhost:11434")


def test_cloud_request_is_stopped_at_outbound_boundary(policy_file, monkeypatch):
    from backend import llm
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: pytest.fail("Data must not reach a cloud request"))
    with pytest.raises(llm.LLMError, match="Cloud AI is disabled"):
        llm._ask_once("private page content", "private instructions", 0)


def test_local_model_redirect_and_proxy_are_blocked(policy_file, monkeypatch):
    import requests
    calls = []
    class Redirect:
        status_code = 302
        def close(self):
            pass
    def fake_request(session, method, url, **kwargs):
        calls.append((session.trust_env, kwargs["allow_redirects"]))
        return Redirect()
    monkeypatch.setattr(requests.Session, "request", fake_request)
    with pytest.raises(privacy.PrivacyError, match="redirect"):
        privacy.local_ai_request("POST", "http://127.0.0.1:11434/api/chat", json={"prompt": "fixture"})
    assert calls == [(False, False)]


def test_privacy_controls_are_locked_during_a_run(policy_file):
    app = FastAPI()
    jobs = {1: {"status": "running"}}
    register_privacy_api(app, jobs, threading.Lock(), MCPPresence())
    with TestClient(app) as client:
        response = client.put("/api/settings/privacy", json={"mode": "cloud", "cloud_consent": True})
        assert response.status_code == 409
        assert not policy_file.exists()
        jobs.clear()
        assert client.put("/api/settings/privacy", json={"mode": "cloud"}).status_code == 422
        assert not policy_file.exists()


def test_presence_expires_and_never_claims_assistant_location_verified(policy_file, monkeypatch):
    from backend import privacy_api
    clock = [1000.0]
    monkeypatch.setattr(privacy_api.time, "time", lambda: clock[0])
    presence = MCPPresence()
    presence.touch("a" * 32, active=True)
    assert presence.status()["status"] == "blocked"
    privacy.save_policy(privacy.PrivacyPolicy(allow_mcp=True, local_assistant_confirmed=True))
    assert presence.status()["status"] == "active"
    assert presence.status()["location_verified"] is False
    clock[0] += 40
    assert presence.status()["status"] == "offline"


def test_mcp_cannot_read_history_or_approve_its_own_access(policy_file):
    from backend import server
    with TestClient(server.app, base_url="http://127.0.0.1") as client:
        headers = {"X-Agentic-QA": "1", "X-BlowAI-Client": "mcp"}
        assert client.get("/api/history", headers=headers).status_code == 403
        assert client.get("/api/mcp/info", headers=headers).status_code == 200
        assert client.put("/api/settings/privacy", headers=headers,
                          json={"mode": "cloud", "cloud_consent": True, "allow_mcp": True}).status_code == 403
        assert not policy_file.exists()


def test_direct_web_and_android_cloud_requests_are_rejected_before_automation(policy_file, monkeypatch):
    from backend import server
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: pytest.fail("Must not start a worker"))
    with TestClient(server.app, base_url="http://127.0.0.1") as client:
        headers = {"X-Agentic-QA": "1"}
        web = client.post("/api/runs", headers=headers,
                          json={"source": "https://example.test", "authorized": True, "llm_provider": "openai"})
        assert web.status_code == 403
        android = client.post("/api/mobile/runs", headers=headers, data={
            "app_mode": "installed", "device_id": "fixture", "package_name": "com.example.fixture",
            "authorized": "true", "llm_provider": "openai"})
        assert android.status_code == 403
