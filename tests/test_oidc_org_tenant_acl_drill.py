"""OIDC org/hd tenant ACL stays incomplete for Gate I."""
from backend.oidc_org_tenant_acl_drill import run_oidc_org_tenant_acl_drill


def test_oidc_org_tenant_acl_stays_partial(tmp_path):
    evidence = run_oidc_org_tenant_acl_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["ok"] is True
    assert evidence["passed"] == 2
    assert (tmp_path / "oidc_org_tenant_acl_drill.json").is_file()
