"""Hosted CI concurrency contract stays incomplete for Gates D/F."""
from backend.hosted_ci_concurrency_contract_drill import (
    run_hosted_ci_concurrency_contract_drill,
)


def test_hosted_ci_concurrency_contract_stays_partial(tmp_path):
    evidence = run_hosted_ci_concurrency_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["live_hosted_runners"] is False
    assert evidence["ok"] is True
    assert evidence["android"]["checks"]["manual_only"] is True
    assert evidence["browsers"]["checks"]["automatic_final_trigger"] is True
    assert evidence["browsers"]["concurrency_group_declared"] is True
    assert evidence["browsers"]["cancel_in_progress_declared"] is True
    assert (tmp_path / "hosted_ci_concurrency_contract_drill.json").is_file()
