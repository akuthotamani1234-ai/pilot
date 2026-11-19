"""An access matrix stays in this install. A link is left unwritten."""
from backend.blueprint_progress import progress
from backend.oidc_acl_matrix_pack_drill import run_oidc_acl_matrix_pack_drill


def test_an_access_matrix_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.oidc_email_domain_tenant_acl_drill as email
    import backend.oidc_groups_role_acl_drill as groups
    import backend.oidc_org_tenant_acl_drill as org
    import backend.oidc_tid_tenant_acl_drill as tid

    secret = "tenant-b-matrix"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "oidc_acl_matrix_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_oidc_acl_matrix_pack_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_i_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_oidc_acl_matrix_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()

    monkeypatch.setattr(tid, "run_oidc_tid_tenant_acl_drill", lambda ops_dir=None: {"ok": True})
    monkeypatch.setattr(
        email, "run_oidc_email_domain_tenant_acl_drill", lambda ops_dir=None: {"ok": True},
    )
    monkeypatch.setattr(org, "run_oidc_org_tenant_acl_drill", lambda ops_dir=None: {"ok": True})
    monkeypatch.setattr(
        groups, "run_oidc_groups_role_acl_drill", lambda ops_dir=None: {"ok": True},
    )
    planted.unlink()
    saved = run_oidc_acl_matrix_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_i_complete"] is False
    assert saved["ok"] is True
    assert saved["parts"]["tid"] is True
    assert "ACL matrix pack ok" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_acl_matrix_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-acl-matrix-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-acl-matrix-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "I")["status"] != "done"
    assert snap["complete"] is False
