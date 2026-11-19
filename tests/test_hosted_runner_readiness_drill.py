"""Hosted runner readiness scores stay incomplete for Gates D/F."""
from backend.hosted_runner_readiness_drill import run_hosted_runner_readiness_drill


def test_hosted_runner_readiness_stays_partial(tmp_path):
    evidence = run_hosted_runner_readiness_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["multi_device"]["live_hosted_runners"] is False
    assert evidence["multi_browser"]["live_hosted_runners"] is False
    assert evidence["multi_device"]["score_of"] == 8
    assert evidence["multi_browser"]["score_of"] == 6
    assert (tmp_path / "hosted_runner_readiness_drill.json").is_file()
