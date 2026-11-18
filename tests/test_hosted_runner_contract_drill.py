from pathlib import Path

from backend.hosted_runner_contract_drill import run_hosted_runner_contract_drill


def test_hosted_runner_contracts_stay_incomplete(tmp_path: Path):
    evidence = run_hosted_runner_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert evidence.get("ok") is True
    assert (tmp_path / "multi_browser_ci_contract.json").is_file()
    assert (tmp_path / "multi_device_ci_contract.json").is_file()
    assert evidence["multi_browser"]["workflow_exists"] is True
    assert evidence["multi_device"]["workflow_exists"] is True
