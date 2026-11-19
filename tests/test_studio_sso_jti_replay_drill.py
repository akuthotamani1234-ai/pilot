"""Studio SSO jti replay rejection stays incomplete for Gate I."""
import base64
import json
import time

from backend.oidc_jwt import reset_seen_jti, validate_bearer
from backend.studio_sso_jti_replay_drill import run_studio_sso_jti_replay_drill


def _jwt(payload: dict) -> str:
    def enc(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(payload)}.sig"


def test_jti_replay_rejects_second_use(monkeypatch):
    monkeypatch.setenv("QPILOT_SSO_REPLAY_JTI", "1")
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", "https://idp.example")
    reset_seen_jti()
    token = _jwt({
        "iss": "https://idp.example",
        "sub": "user-1",
        "exp": int(time.time()) + 600,
        "jti": "once",
    })
    first = validate_bearer(token, verify_signature=False)
    second = validate_bearer(token, verify_signature=False)
    missing = validate_bearer(
        _jwt({"iss": "https://idp.example", "exp": int(time.time()) + 600}),
        verify_signature=False,
    )
    reset_seen_jti()
    assert first["ok"] is True
    assert second["ok"] is False
    assert second["reason"] == "jti replay rejected"
    assert missing["ok"] is False
    assert "jti required" in missing["reason"]


def test_a_rejected_signature_does_not_use_up_the_jti(monkeypatch):
    monkeypatch.setenv("QPILOT_SSO_REPLAY_JTI", "1")
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", "https://idp.example")
    reset_seen_jti()
    token = _jwt({
        "iss": "https://idp.example",
        "sub": "user-1",
        "exp": int(time.time()) + 600,
        "jti": "still-good",
    })
    forged = validate_bearer(token, verify_signature=True)
    again = validate_bearer(token, verify_signature=True)
    accepted = validate_bearer(token, verify_signature=False)
    reset_seen_jti()
    assert forged["ok"] is False
    assert "signature" in forged["reason"]
    assert again["ok"] is False
    assert "replay" not in again["reason"]
    assert accepted["ok"] is True


def test_jti_replay_off_by_default(monkeypatch):
    monkeypatch.delenv("QPILOT_SSO_REPLAY_JTI", raising=False)
    monkeypatch.setenv("QPILOT_OIDC_ISSUER", "https://idp.example")
    reset_seen_jti()
    token = _jwt({
        "iss": "https://idp.example",
        "exp": int(time.time()) + 600,
        "jti": "repeat-ok",
    })
    assert validate_bearer(token, verify_signature=False)["ok"] is True
    assert validate_bearer(token, verify_signature=False)["ok"] is True


def test_studio_sso_jti_replay_stays_partial(tmp_path, monkeypatch):
    monkeypatch.delenv("QPILOT_OIDC_AUDIENCE", raising=False)
    evidence = run_studio_sso_jti_replay_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["replay_rejected"] is True
    assert (tmp_path / "studio_sso_jti_replay_drill.json").is_file()
