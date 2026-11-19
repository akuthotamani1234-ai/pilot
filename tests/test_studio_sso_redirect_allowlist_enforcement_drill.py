"""Studio SSO redirect allowlist enforcement stays incomplete for Gate I."""
from fastapi.testclient import TestClient

from backend import server
from backend.studio_oidc_callback import validate_redirect_uri
from backend.studio_sso_redirect_allowlist_enforcement_drill import (
    run_studio_sso_redirect_allowlist_enforcement_drill,
)


def test_validate_redirect_uri_rejects_unlisted():
    allow = "http://127.0.0.1/api/sso/callback"
    good = validate_redirect_uri("http://127.0.0.1/api/sso/callback", allowlist=allow)
    bad = validate_redirect_uri("https://evil.example/cb", allowlist=allow)
    unset = validate_redirect_uri("https://evil.example/cb", allowlist="")
    assert good["ok"] is True and good["redirect_ok"] is True
    assert bad["ok"] is False and bad["reason"] == "redirect_uri not allowlisted"
    assert unset["ok"] is True and unset["redirect_enforced"] is False


def test_callback_rejects_unlisted_redirect_query(monkeypatch):
    monkeypatch.setenv(
        "QPILOT_OIDC_REDIRECT_ALLOWLIST",
        "http://127.0.0.1/api/sso/callback",
    )
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    response = client.get(
        "/api/sso/callback",
        params={"code": "abc", "redirect_uri": "https://evil.example/cb"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False
    assert body["gate_i_complete"] is False
    assert body["reason"] == "redirect_uri not allowlisted"


def test_callback_ignores_redirect_when_allowlist_unset(monkeypatch):
    monkeypatch.delenv("QPILOT_OIDC_REDIRECT_ALLOWLIST", raising=False)
    monkeypatch.delenv("QPILOT_OIDC_TOKEN_URL", raising=False)
    monkeypatch.delenv("QPILOT_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("BLOWAI_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    started = client.post("/api/sso/login", headers={"X-Agentic-QA": "1"}).json()
    response = client.get(
        "/api/sso/callback",
        params={
            "code": "abc",
            "state": started["state"],
            "redirect_uri": "https://evil.example/cb",
        },
    )
    body = response.json()
    assert body["reason"] != "redirect_uri not allowlisted"
    assert "not configured" in body["reason"]
    assert body["gate_i_complete"] is False


def test_studio_sso_redirect_allowlist_enforcement_stays_partial(tmp_path):
    evidence = run_studio_sso_redirect_allowlist_enforcement_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["bad_rejected"] is True
    assert (
        tmp_path / "studio_sso_redirect_allowlist_enforcement_drill.json"
    ).is_file()
