"""Studio SSO token expiry stays incomplete for Gate I."""
from backend.studio_sso_token_expiry_drill import run_studio_sso_token_expiry_drill


def test_studio_sso_token_expiry_stays_partial(tmp_path):
    evidence = run_studio_sso_token_expiry_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["fresh_ok"] is True
    assert evidence["expired_rejected"] is True
    assert (tmp_path / "studio_sso_token_expiry_drill.json").is_file()
