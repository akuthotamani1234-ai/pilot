"""Studio SSO principal bootstrap stays incomplete for Gate I."""
from backend.studio_sso_principal_bootstrap_drill import (
    run_studio_sso_principal_bootstrap_drill,
)


def test_studio_sso_principal_bootstrap_stays_partial(tmp_path):
    evidence = run_studio_sso_principal_bootstrap_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["ok"] is True
    assert evidence["bootstrapped"]["was_missing"] is True
    assert (tmp_path / "studio_sso_principal_bootstrap_drill.json").is_file()
