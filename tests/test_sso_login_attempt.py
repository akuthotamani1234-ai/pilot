"""A Studio callback is refused unless it continues a login this process started."""
import base64
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

from fastapi.testclient import TestClient

from backend import server
from backend.studio_oidc_callback import (
    consume_sso_login,
    issue_sso_login,
    reset_sso_logins,
    reset_used_authorization_codes,
)
from backend.tenancy_store import get_principal, upsert_tenant


def test_a_callback_without_a_started_login_does_not_call_the_token_endpoint(monkeypatch):
    monkeypatch.setenv("QPILOT_OIDC_TOKEN_URL", "http://127.0.0.1:9/token")

    def fail_open(*_args, **_kwargs):
        raise AssertionError("token endpoint must not be called")

    monkeypatch.setattr(urllib.request, "urlopen", fail_open)
    reset_sso_logins()
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    response = client.get("/api/sso/callback", params={"code": "stolen", "state": "other-browser"})
    body = response.json()
    assert body["ok"] is False
    assert body["gate_i_complete"] is False
    assert body["reason"] == "SSO login state was not issued"


def test_a_started_login_is_single_use_and_expires():
    reset_sso_logins()
    started = issue_sso_login()
    assert started["gate_i_complete"] is False
    assert started["state"] and started["nonce"]
    taken = consume_sso_login(started["state"])
    assert taken["ok"] is True
    assert taken["nonce"] == started["nonce"]
    again = consume_sso_login(started["state"])
    assert again["ok"] is False
    assert again["reason"] == "SSO login state was not issued"
    stale = issue_sso_login()
    expired = consume_sso_login(stale["state"], now=10**12)
    assert expired["ok"] is False
    assert expired["reason"] == "SSO login state expired"
    reset_sso_logins()


def test_a_callback_nonce_must_match_the_login_it_started(monkeypatch, tmp_path):
    db = tmp_path / "tenancy.sqlite"
    upsert_tenant("t1", "Tenant", db_path=db)
    monkeypatch.setenv("QPILOT_OIDC_TOKEN_URL", "http://127.0.0.1:9/token")
    monkeypatch.delenv("QPILOT_OIDC_PKCE_REQUIRED", raising=False)
    monkeypatch.delenv("QPILOT_SSO_EXPECTED_STATE", raising=False)
    monkeypatch.delenv("QPILOT_OIDC_REDIRECT_ALLOWLIST", raising=False)
    monkeypatch.delenv("QPILOT_SSO_EXPECTED_NONCE", raising=False)
    import backend.tenancy_store as tenancy
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)

    class _Body:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"id_token": "tok", "token_type": "Bearer"}).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Body())
    monkeypatch.setattr(
        "backend.oidc_jwt.validate_bearer",
        lambda *_a, **_k: {
            "ok": True,
            "signature_verified": True,
            "claims": {"sub": "paste-1", "tid": "t1", "email": "p@ex.test", "nonce": "from-another-login"},
        },
    )
    reset_sso_logins()
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    started = client.post("/api/sso/login", headers={"X-Agentic-QA": "1"}).json()
    refused = client.get(
        "/api/sso/callback",
        params={"code": "code-from-idp", "state": started["state"]},
    ).json()
    assert refused["ok"] is False
    assert refused["gate_i_complete"] is False
    assert refused["nonce_ok"] is False
    assert get_principal("paste-1", db_path=db) is None
    reset_sso_logins()


def test_the_pkce_verifier_stays_on_the_server(monkeypatch):
    monkeypatch.setenv("QPILOT_OIDC_TOKEN_URL", "http://127.0.0.1:9/token")
    monkeypatch.delenv("QPILOT_OIDC_PKCE_REQUIRED", raising=False)
    monkeypatch.delenv("QPILOT_SSO_EXPECTED_STATE", raising=False)
    monkeypatch.delenv("QPILOT_OIDC_REDIRECT_ALLOWLIST", raising=False)
    monkeypatch.delenv("QPILOT_SSO_EXPECTED_NONCE", raising=False)
    seen = {}

    def capture(req, timeout=10):
        seen["data"] = req.data
        seen["timeout"] = timeout
        raise urllib.error.URLError("stop")

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    reset_sso_logins()
    reset_used_authorization_codes()
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    started = client.post("/api/sso/login", headers={"X-Agentic-QA": "1"}).json()
    assert started["gate_i_complete"] is False
    assert started.get("code_challenge")
    assert started.get("code_challenge_method") == "S256"
    assert "code_verifier" not in started
    body = client.get(
        "/api/sso/callback",
        params={"code": "code-pkce-stays", "state": started["state"], "code_verifier": "from-the-query"},
    ).json()
    assert "data" in seen, body
    posted = urllib.parse.parse_qs(seen["data"].decode())
    verifier = posted["code_verifier"][0]
    assert verifier != "from-the-query"
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert challenge == started["code_challenge"]
    reset_sso_logins()
