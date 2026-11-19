"""Studio SSO authorization-code reuse stays incomplete for Gate I."""
from backend.studio_oidc_callback import (
    exchange_code,
    note_authorization_code_used,
    reset_used_authorization_codes,
)
from backend.studio_sso_code_reuse_drill import run_studio_sso_code_reuse_drill


def test_reused_authorization_code_rejected_before_exchange():
    reset_used_authorization_codes()
    note_authorization_code_used("once")
    reused = exchange_code(code="once")
    reset_used_authorization_codes()
    assert reused["ok"] is False
    assert reused["gate_i_complete"] is False
    assert reused["code_reused"] is True
    assert reused["reason"] == "authorization code already used"


def test_studio_sso_code_reuse_stays_partial(tmp_path):
    evidence = run_studio_sso_code_reuse_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["reuse_rejected"] is True
    assert (tmp_path / "studio_sso_code_reuse_drill.json").is_file()
