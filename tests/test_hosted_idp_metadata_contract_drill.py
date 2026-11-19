"""Hosted IdP metadata contract stays incomplete for Gate I."""
from backend.hosted_idp_metadata_contract_drill import (
    LOCAL_PARTIAL,
    REQUIRED_FIELDS,
    run_hosted_idp_metadata_contract_drill,
)


def test_hosted_idp_metadata_contract_stays_partial(tmp_path, monkeypatch):
    import backend.hosted_idp_metadata_contract_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in LOCAL_PARTIAL:
        (ops / name).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_hosted_idp_metadata_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["ok"] is True
    assert "jwks_uri" in REQUIRED_FIELDS
    assert (tmp_path / "hosted_idp_metadata_contract_drill.json").is_file()
