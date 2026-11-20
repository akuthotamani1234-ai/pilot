"""Gate I/G SSO tenant ACL stays incomplete; needs PyJWT."""
from pathlib import Path

import pytest

pytest.importorskip("jwt")

from backend.sso_tenant_acl_drill import run_sso_tenant_acl_drill


def test_sso_tenant_acl_drill_reports_honestly(tmp_path: Path):
    evidence = run_sso_tenant_acl_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["gate_g_complete"] is False
    assert (tmp_path / "sso_tenant_acl_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence["acl"]["same_tenant_allowed"] is True
    assert evidence["acl"]["cross_tenant_denied"] is True
