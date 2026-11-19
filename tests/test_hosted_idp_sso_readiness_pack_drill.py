"""Hosted IdP SSO readiness pack stays incomplete for Gate I."""
from backend.hosted_idp_sso_readiness_pack_drill import (
    run_hosted_idp_sso_readiness_pack_drill,
)


def test_hosted_idp_sso_readiness_pack_stays_partial(tmp_path, monkeypatch):
    import backend.hosted_idp_claim_map_completeness_drill as claim
    import backend.hosted_idp_contract_drill as contract
    import backend.hosted_idp_readiness_drill as ready
    import backend.oidc_acl_matrix_pack_drill as matrix
    import backend.oidc_email_domain_tenant_acl_drill as email
    import backend.studio_sso_principal_bootstrap_drill as bootstrap

    monkeypatch.setattr(
        matrix, "run_oidc_acl_matrix_pack_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        claim, "run_hosted_idp_claim_map_completeness_drill",
        lambda ops_dir=None: {"ok": True, "score": 8, "score_of": 8},
    )
    monkeypatch.setattr(
        contract, "run_hosted_idp_contract_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        ready, "run_hosted_idp_readiness_drill",
        lambda ops_dir=None: {"ok": True, "score": 19, "score_of": 19},
    )
    monkeypatch.setattr(
        bootstrap, "run_studio_sso_principal_bootstrap_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        email, "run_oidc_email_domain_tenant_acl_drill",
        lambda ops_dir=None: {"ok": True},
    )
    evidence = run_hosted_idp_sso_readiness_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "hosted_idp_sso_readiness_pack_drill.json").is_file()
