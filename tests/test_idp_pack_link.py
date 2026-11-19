"""An IdP readiness pack stays in this install. A link is left unwritten."""
from backend.blueprint_progress import progress
from backend.hosted_idp_sso_readiness_pack_drill import (
    run_hosted_idp_sso_readiness_pack_drill,
)


def _pass(**_kwargs):
    return {"ok": True}


def test_an_idp_readiness_pack_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.hosted_idp_claim_map_completeness_drill as claim
    import backend.hosted_idp_contract_drill as contract
    import backend.hosted_idp_readiness_drill as ready
    import backend.oidc_acl_matrix_pack_drill as matrix
    import backend.oidc_email_domain_tenant_acl_drill as email
    import backend.studio_sso_principal_bootstrap_drill as bootstrap

    secret = "tenant-b-idp-pack"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "hosted_idp_sso_readiness_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_hosted_idp_sso_readiness_pack_drill(ops_dir=linked)
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
    skipped = run_hosted_idp_sso_readiness_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()

    monkeypatch.setattr(matrix, "run_oidc_acl_matrix_pack_drill", _pass)
    monkeypatch.setattr(claim, "run_hosted_idp_claim_map_completeness_drill", _pass)
    monkeypatch.setattr(contract, "run_hosted_idp_contract_drill", _pass)
    monkeypatch.setattr(ready, "run_hosted_idp_readiness_drill", _pass)
    monkeypatch.setattr(bootstrap, "run_studio_sso_principal_bootstrap_drill", _pass)
    monkeypatch.setattr(email, "run_oidc_email_domain_tenant_acl_drill", _pass)
    planted.unlink()
    saved = run_hosted_idp_sso_readiness_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_i_complete"] is False
    assert saved["live_hosted_sso"] is False
    assert saved["ok"] is True
    assert saved["parts"]["contract"] is True
    assert "readiness pack ok" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_idp_pack_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-idp-pack-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-idp-pack-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "I")["status"] != "done"
    assert snap["complete"] is False
