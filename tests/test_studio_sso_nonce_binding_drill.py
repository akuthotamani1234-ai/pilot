"""Studio SSO nonce binding stays incomplete for Gate I."""
from backend.studio_oidc_callback import validate_sso_nonce
from backend.studio_sso_nonce_binding_drill import run_studio_sso_nonce_binding_drill


def test_validate_sso_nonce_rejects_mismatch():
    good = validate_sso_nonce("abc", expected="abc")
    bad = validate_sso_nonce("xyz", expected="abc")
    unset = validate_sso_nonce("xyz", expected="")
    assert good["ok"] is True and good["nonce_ok"] is True
    assert bad["ok"] is False and bad["reason"] == "nonce mismatch"
    assert unset["ok"] is True and unset["nonce_enforced"] is False


def test_studio_sso_nonce_binding_stays_partial(tmp_path):
    evidence = run_studio_sso_nonce_binding_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert evidence["bad_rejected"] is True
    assert (tmp_path / "studio_sso_nonce_binding_drill.json").is_file()
