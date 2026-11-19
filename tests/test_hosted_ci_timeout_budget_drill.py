"""Hosted CI timeout budget stays incomplete for Gates D/F."""
from backend.hosted_ci_timeout_budget_drill import run_hosted_ci_timeout_budget_drill


def test_hosted_ci_timeout_budget_stays_partial(tmp_path):
    evidence = run_hosted_ci_timeout_budget_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["live_hosted_runners"] is False
    assert evidence["ok"] is True
    assert evidence["android"]["timeout_minutes"] == 90
    assert evidence["browsers"]["timeout_minutes"] == 45
    assert (tmp_path / "hosted_ci_timeout_budget_drill.json").is_file()
