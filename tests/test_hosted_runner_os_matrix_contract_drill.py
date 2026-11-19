"""Hosted runner OS matrix contract stays incomplete for Gates D/F."""
from backend.hosted_runner_os_matrix_contract_drill import (
    run_hosted_runner_os_matrix_contract_drill,
)


def test_hosted_runner_os_matrix_contract_stays_partial(tmp_path):
    evidence = run_hosted_runner_os_matrix_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence["live_hosted_runners"] is False
    assert evidence["ok"] is True
    assert any("ubuntu" in r for r in evidence["android"]["runs_on"])
    assert any("ubuntu" in r for r in evidence["browsers"]["runs_on"])
    assert (tmp_path / "hosted_runner_os_matrix_contract_drill.json").is_file()
