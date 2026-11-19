"""OIDC ACL matrix pack stays incomplete for Gate I."""
from backend.oidc_acl_matrix_pack_drill import run_oidc_acl_matrix_pack_drill


def test_oidc_acl_matrix_pack_stays_partial(tmp_path, monkeypatch):
    import backend.oidc_email_domain_tenant_acl_drill as email
    import backend.oidc_groups_role_acl_drill as groups
    import backend.oidc_org_tenant_acl_drill as org
    import backend.oidc_tid_tenant_acl_drill as tid

    monkeypatch.setattr(
        tid, "run_oidc_tid_tenant_acl_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        email, "run_oidc_email_domain_tenant_acl_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        org, "run_oidc_org_tenant_acl_drill",
        lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(
        groups, "run_oidc_groups_role_acl_drill",
        lambda ops_dir=None: {"ok": True},
    )
    evidence = run_oidc_acl_matrix_pack_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert (tmp_path / "oidc_acl_matrix_pack_drill.json").is_file()
