from pathlib import Path

from backend.dual_tenant_oidc_acl_drill import run_dual_tenant_oidc_acl_drill


def test_dual_tenant_oidc_acl_reports_honestly(tmp_path: Path):
    evidence = run_dual_tenant_oidc_acl_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["gate_g_complete"] is False
    assert (tmp_path / "dual_tenant_oidc_acl_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("passed") == evidence.get("total") == 2
