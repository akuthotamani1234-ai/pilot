"""Hosted IdP SSO readiness pack stays incomplete for Gate I."""
from backend.hosted_idp_sso_readiness_pack_drill import (
    run_hosted_idp_sso_readiness_pack_drill,
)


def test_hosted_idp_sso_readiness_pack_stays_partial(tmp_path):
    evidence = run_hosted_idp_sso_readiness_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "hosted_idp_sso_readiness_pack_drill.json").is_file()
