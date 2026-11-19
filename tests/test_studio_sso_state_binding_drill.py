"""Studio SSO state binding stays incomplete for Gate I."""
from backend.studio_oidc_callback import validate_sso_state
from backend.studio_sso_state_binding_drill import run_studio_sso_state_binding_drill


def test_validate_sso_state_rejects_mismatch():
    good = validate_sso_state("abc", expected="abc")
    bad = validate_sso_state("xyz", expected="abc")
    assert good["ok"] is True and good["state_ok"] is True
    assert bad["ok"] is False and bad["reason"] == "state mismatch"


def test_studio_sso_state_binding_stays_partial(tmp_path):
    evidence = run_studio_sso_state_binding_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["bad_rejected"] is True
    assert (tmp_path / "studio_sso_state_binding_drill.json").is_file()
