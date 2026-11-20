"""Gate I SSO contract stays incomplete without live IdP proof."""
from backend.dashboard_sso import snapshot


def test_sso_snapshot_incomplete_when_unset(monkeypatch):
    for name in (
        "QPILOT_OIDC_ISSUER", "BLOWAI_OIDC_ISSUER", "OIDC_ISSUER",
        "QPILOT_OIDC_CLIENT_ID", "BLOWAI_OIDC_CLIENT_ID", "OIDC_CLIENT_ID",
        "QPILOT_OIDC_AUDIENCE", "BLOWAI_OIDC_AUDIENCE", "OIDC_AUDIENCE",
        "QPILOT_DASHBOARD_HOST", "BLOWAI_DASHBOARD_HOST", "DASHBOARD_PUBLIC_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    snap = snapshot()
    assert snap["gate_i_complete"] is False
    assert snap["ready"] is False
    assert snap["configured"] is False


def test_sso_env_present_still_not_ready(monkeypatch):
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", "https://idp.example/realms/qpilot")
    monkeypatch.setenv("QPILOT_OIDC_CLIENT_ID", "qpilot-dashboard")
    snap = snapshot()
    assert snap["configured"] is True
    assert snap["ready"] is False
    assert snap["gate_i_complete"] is False
