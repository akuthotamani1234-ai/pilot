"""Studio SSO nbf rejection stays incomplete for Gate I."""
import base64
import json
import time

from backend.oidc_jwt import validate_bearer
from backend.studio_sso_nbf_drill import run_studio_sso_nbf_drill


def _jwt(payload: dict) -> str:
    def enc(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(payload)}.sig"


def test_rejects_future_nbf(monkeypatch):
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", "https://idp.example")
    monkeypatch.delenv("QPILOT_OIDC_AUDIENCE", raising=False)
    now = int(time.time())
    current = validate_bearer(
        _jwt({"iss": "https://idp.example", "exp": now + 600, "nbf": now}),
        verify_signature=False,
    )
    future = validate_bearer(
        _jwt({"iss": "https://idp.example", "exp": now + 600, "nbf": now + 120}),
        verify_signature=False,
    )
    assert current["ok"] is True
    assert future["ok"] is False
    assert future["reason"] == "token not yet valid"


def test_studio_sso_nbf_stays_partial(tmp_path, monkeypatch):
    monkeypatch.delenv("QPILOT_OIDC_AUDIENCE", raising=False)
    evidence = run_studio_sso_nbf_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["future_rejected"] is True
    assert (tmp_path / "studio_sso_nbf_drill.json").is_file()
