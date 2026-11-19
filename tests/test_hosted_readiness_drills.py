"""Hosted IdP / on-call readiness scores stay incomplete."""
from backend.hosted_idp_readiness_drill import run_hosted_idp_readiness_drill
from backend.hosted_oncall_readiness_drill import run_hosted_oncall_readiness_drill


def test_hosted_idp_readiness_stays_partial(tmp_path):
    evidence = run_hosted_idp_readiness_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["live_hosted_sso"] is False
    assert evidence["score_of"] == 9
    assert (tmp_path / "hosted_idp_readiness_drill.json").is_file()


def test_hosted_oncall_readiness_stays_partial(tmp_path):
    evidence = run_hosted_oncall_readiness_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["live_hosted_paging"] is False
    assert evidence["score_of"] == 10
    assert (tmp_path / "hosted_oncall_readiness_drill.json").is_file()
