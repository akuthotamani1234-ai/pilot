"""A two-tenant access check stays in this install. A link is left unwritten."""
import pytest

pytest.importorskip("jwt")

from backend.blueprint_progress import progress
from backend.dual_tenant_oidc_acl_drill import run_dual_tenant_oidc_acl_drill


def test_a_two_tenant_access_check_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-dual"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "dual_tenant_oidc_acl_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_dual_tenant_oidc_acl_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_i_complete"] is False
    assert refused["gate_g_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_dual_tenant_oidc_acl_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()

    planted.unlink()
    saved = run_dual_tenant_oidc_acl_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_i_complete"] is False
    assert saved["gate_g_complete"] is False
    assert saved["ok"] is True
    assert saved["passed"] == 2
    assert "reciprocal deny" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_dual_tenant_acl_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-dual-tenant-acl-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-dual-tenant-acl-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "I")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
