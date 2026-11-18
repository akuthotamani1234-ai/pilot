"""Gate I optional dashboard auth modes."""
from backend.dashboard_auth import auth_mode, authorize, required, snapshot
from backend.tenancy_store import upsert_principal, upsert_tenant


def test_unset_token_allows_localhost(monkeypatch):
    monkeypatch.delenv("QPILOT_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("BLOWAI_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("QPILOT_DASHBOARD_AUTH", raising=False)
    monkeypatch.delenv("WEBHOOK_TOKEN", raising=False)
    assert required() is False
    assert auth_mode() == "none"
    assert authorize(None)["ok"] is True
    assert snapshot()["gate_i_complete"] is False


def test_configured_token_requires_bearer(monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_TOKEN", "secret-token")
    monkeypatch.delenv("QPILOT_DASHBOARD_AUTH", raising=False)
    assert required() is True
    assert authorize(None)["ok"] is False
    assert authorize("Bearer wrong")["ok"] is False
    assert authorize("Bearer secret-token")["ok"] is True


def test_webhook_mode_accepts_x_qa_token(monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "webhook")
    monkeypatch.setenv("WEBHOOK_TOKEN", "hook-secret")
    monkeypatch.delenv("QPILOT_DASHBOARD_TOKEN", raising=False)
    assert authorize(None, x_qa_token="hook-secret")["ok"] is True
    assert authorize("Bearer hook-secret")["ok"] is True
    assert authorize(None, x_qa_token="nope")["ok"] is False


def test_principal_mode_uses_rbac(monkeypatch, tmp_path):
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    db = tmp_path / "auth.sqlite"
    import backend.tenancy_store as ts
    monkeypatch.setattr(ts, "DEFAULT_DB", db)
    upsert_tenant("t1", "Tenant", db_path=db)
    upsert_principal("p-op", "t1", "op@ex.test", "operator", db_path=db)
    upsert_principal("p-view", "t1", "v@ex.test", "viewer", db_path=db)
    assert authorize("Bearer p-op")["ok"] is True
    assert authorize("Bearer p-view")["ok"] is False  # viewer lacks review.write
    assert authorize("Bearer missing")["ok"] is False
