"""Gate I optional dashboard bearer token."""
from backend.dashboard_auth import authorize, required, snapshot


def test_unset_token_allows_localhost(monkeypatch):
    monkeypatch.delenv("QPILOT_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("BLOWAI_DASHBOARD_TOKEN", raising=False)
    assert required() is False
    assert authorize(None)["ok"] is True
    assert snapshot()["gate_i_complete"] is False


def test_configured_token_requires_bearer(monkeypatch):
    monkeypatch.setenv("QPILOT_DASHBOARD_TOKEN", "secret-token")
    assert required() is True
    assert authorize(None)["ok"] is False
    assert authorize("Bearer wrong")["ok"] is False
    assert authorize("Bearer secret-token")["ok"] is True
