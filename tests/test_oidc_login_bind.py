"""SSO login binds a principal from groups and never raises an existing role."""
import json
import urllib.request

from backend.dashboard_auth import authorize, bind_login_principal
from backend.studio_oidc_callback import exchange_code, reset_used_authorization_codes
from backend.tenancy_store import get_principal, upsert_principal, upsert_tenant


def test_first_login_creates_the_group_role_and_a_later_login_cannot_raise(tmp_path):
    db = tmp_path / "tenancy.sqlite"
    created = bind_login_principal({
        "sub": "view-1", "tid": "t1", "email": "v@ex.test",
        "groups": ["qpilot-viewers", "qpilot-admins"],
    }, db_path=db)
    assert created["created"] is True
    assert created["role"] == "viewer"
    raised = bind_login_principal({
        "sub": "view-1", "tid": "t1", "email": "v@ex.test",
        "groups": ["qpilot-admins"],
    }, db_path=db)
    assert raised["created"] is False
    assert raised["role"] == "viewer"
    assert get_principal("view-1", db_path=db)["role"] == "viewer"
    missing = bind_login_principal({
        "sub": "new-1", "tid": "t1", "email": "n@ex.test", "groups": ["other"],
    }, db_path=db)
    assert missing["principal_bound"] is False
    assert get_principal("new-1", db_path=db) is None


def test_exchange_binds_a_new_principal_and_leaves_a_stored_role(monkeypatch, tmp_path):
    db = tmp_path / "tenancy.sqlite"
    upsert_tenant("t1", "Tenant", db_path=db)
    upsert_principal("kept-1", "t1", "kept@ex.test", "viewer", db_path=db)
    monkeypatch.setenv("QPILOT_OIDC_TOKEN_URL", "http://127.0.0.1:9/token")
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "oidc")
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("QPILOT_OIDC_AUDIENCE", "qpilot-dashboard")
    monkeypatch.delenv("QPILOT_OIDC_PKCE_REQUIRED", raising=False)
    monkeypatch.delenv("QPILOT_SSO_EXPECTED_STATE", raising=False)
    monkeypatch.delenv("QPILOT_OIDC_REDIRECT_ALLOWLIST", raising=False)
    monkeypatch.delenv("QPILOT_SSO_EXPECTED_NONCE", raising=False)
    import backend.tenancy_store as tenancy
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)

    claims = {}

    class _Body:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"id_token": "tok", "token_type": "Bearer"}).encode()

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _Body())

    def fake_validate(_token, verify_signature=True):
        assert verify_signature is True
        return {"ok": True, "signature_verified": True, "claims": dict(claims)}

    monkeypatch.setattr("backend.oidc_jwt.validate_bearer", fake_validate)
    reset_used_authorization_codes()
    claims.update({
        "iss": "https://idp.example", "aud": "qpilot-dashboard",
        "sub": "new-admin", "tid": "t1", "email": "a@ex.test",
        "groups": ["qpilot-admins"],
    })
    created = exchange_code(code="code-new", db_path=db)
    assert created["ok"] is True
    assert created["principal_created"] is True
    assert created["role"] == "admin"
    assert created["access_token"] == "tok"
    assert created["gate_i_complete"] is False
    assert authorize("Bearer tok")["ok"] is True

    reset_used_authorization_codes()
    claims.update({"sub": "kept-1", "groups": ["qpilot-admins"], "email": "kept@ex.test"})
    kept = exchange_code(code="code-kept", db_path=db)
    assert kept["principal_created"] is False
    assert kept["role"] == "viewer"
    assert get_principal("kept-1", db_path=db)["role"] == "viewer"
    assert kept["access_token"] == "tok"
    reset_used_authorization_codes()
    claims.update({"sub": "stranger", "groups": ["other-team"], "email": "s@ex.test"})
    stranger = exchange_code(code="code-stranger", db_path=db)
    assert stranger["ok"] is True
    assert stranger["principal_bound"] is False
    assert stranger["access_token"] == ""
    assert "not a known role" in (stranger.get("reason") or "")
    reset_used_authorization_codes()
