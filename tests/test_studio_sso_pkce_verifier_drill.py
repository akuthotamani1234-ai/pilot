"""Studio SSO PKCE verifier stays incomplete for Gate I."""
import urllib.error
import urllib.request

from backend.studio_oidc_callback import exchange_code, token_request_fields
from backend.studio_sso_pkce_verifier_drill import run_studio_sso_pkce_verifier_drill


def test_missing_pkce_verifier_rejected_before_token_endpoint(monkeypatch):
    monkeypatch.setenv("QPILOT_OIDC_PKCE_REQUIRED", "1")
    monkeypatch.delenv("QPILOT_OIDC_CODE_VERIFIER", raising=False)
    monkeypatch.delenv("QPILOT_SSO_EXPECTED_STATE", raising=False)

    def fail_open(*_args, **_kwargs):
        raise AssertionError("token endpoint must not be called")

    monkeypatch.setattr(urllib.request, "urlopen", fail_open)
    missing = exchange_code(code="abc", code_verifier="")
    assert missing["ok"] is False
    assert missing["gate_i_complete"] is False
    assert missing["pkce_required"] is True
    assert missing["reason"] == (
        "code_verifier required when QPILOT_OIDC_PKCE_REQUIRED is set"
    )


def test_code_verifier_is_posted(monkeypatch):
    monkeypatch.setenv("QPILOT_OIDC_PKCE_REQUIRED", "1")
    monkeypatch.setenv("QPILOT_OIDC_TOKEN_URL", "http://127.0.0.1:9/token")
    monkeypatch.delenv("QPILOT_OIDC_CODE_VERIFIER", raising=False)
    monkeypatch.delenv("QPILOT_SSO_EXPECTED_STATE", raising=False)
    monkeypatch.delenv("QPILOT_OIDC_REDIRECT_ALLOWLIST", raising=False)
    seen = {}

    def capture(req, timeout=10):
        seen["data"] = req.data
        seen["timeout"] = timeout
        raise urllib.error.URLError("stop")

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    out = exchange_code(code="abc", code_verifier="verifier-1")
    assert out["ok"] is False
    assert b"code_verifier=verifier-1" in seen["data"]
    assert token_request_fields(
        code="abc",
        client_id="qpilot-studio",
        redirect_uri="http://127.0.0.1/studio/callback",
        code_verifier="verifier-1",
    )["code_verifier"] == "verifier-1"


def test_pkce_off_does_not_require_verifier(monkeypatch):
    monkeypatch.delenv("QPILOT_OIDC_PKCE_REQUIRED", raising=False)
    monkeypatch.delenv("QPILOT_OIDC_CODE_VERIFIER", raising=False)
    monkeypatch.delenv("QPILOT_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("QPILOT_OIDC_TOKEN_URL", raising=False)
    monkeypatch.delenv("OIDC_TOKEN_URL", raising=False)
    monkeypatch.delenv("BLOWAI_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("QPILOT_SSO_EXPECTED_STATE", raising=False)
    out = exchange_code(code="abc")
    assert out["ok"] is False
    assert out.get("pkce_required") is not True
    assert "code_verifier required" not in (out.get("reason") or "")


def test_studio_sso_pkce_verifier_stays_partial(tmp_path):
    evidence = run_studio_sso_pkce_verifier_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["missing_verifier_rejected"] is True
    assert evidence["verifier_on_token_form"] is True
    assert (tmp_path / "studio_sso_pkce_verifier_drill.json").is_file()
