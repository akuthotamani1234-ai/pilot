"""OIDC claim-map completeness stays incomplete for Gate I."""
from backend.hosted_idp_claim_map_completeness_drill import (
    CLAIM_MAP,
    run_hosted_idp_claim_map_completeness_drill,
)


def test_hosted_idp_claim_map_completeness_stays_partial(tmp_path, monkeypatch):
    import backend.hosted_idp_claim_map_completeness_drill as mod

    ops = tmp_path / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for _, artifact, _ in CLAIM_MAP:
        (ops / artifact).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    evidence = run_hosted_idp_claim_map_completeness_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["score_of"] == len(CLAIM_MAP)
    assert evidence["ok"] is True
    assert (tmp_path / "hosted_idp_claim_map_completeness_drill.json").is_file()
