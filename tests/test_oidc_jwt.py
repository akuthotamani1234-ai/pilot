"""Gate I OIDC JWT structural validation stays incomplete."""
import base64
import json
import time

from backend.oidc_jwt import decode_unverified, validate_bearer


def _jwt(payload: dict, header: dict | None = None) -> str:
    def enc(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{enc(header or {'alg': 'none', 'typ': 'JWT'})}.{enc(payload)}.sig"


def test_decode_and_claim_checks(monkeypatch):
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", "https://idp.example")
    monkeypatch.setenv("QPILOT_OIDC_AUDIENCE", "qpilot-dashboard")
    token = _jwt({
        "iss": "https://idp.example",
        "aud": "qpilot-dashboard",
        "sub": "user-1",
        "exp": int(time.time()) + 3600,
        "email": "a@ex.test",
    })
    decoded = decode_unverified(token)
    assert decoded["payload"]["sub"] == "user-1"
    out = validate_bearer(token, verify_signature=False)
    assert out["ok"] is True
    assert out["gate_i_complete"] is False
    assert out["claims"]["email"] == "a@ex.test"


def test_rejects_wrong_issuer(monkeypatch):
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", "https://idp.example")
    monkeypatch.delenv("QPILOT_OIDC_AUDIENCE", raising=False)
    token = _jwt({"iss": "https://other.example", "exp": int(time.time()) + 60})
    out = validate_bearer(token, verify_signature=False)
    assert out["ok"] is False
    assert "iss mismatch" in out["reason"]


def test_rejects_expired(monkeypatch):
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", "https://idp.example")
    token = _jwt({"iss": "https://idp.example", "exp": int(time.time()) - 10})
    out = validate_bearer(token, verify_signature=False)
    assert out["ok"] is False
    assert "expired" in out["reason"]
