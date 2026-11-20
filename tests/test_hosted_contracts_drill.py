from pathlib import Path

from backend.hosted_idp_contract_drill import run_hosted_idp_contract_drill
from backend.hosted_oncall_contract_drill import run_hosted_oncall_contract_drill


def test_hosted_idp_contract_stays_incomplete(tmp_path: Path):
    evidence = run_hosted_idp_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence.get("kind") == "contract_only"
    assert (tmp_path / "hosted_idp_contract_drill.json").is_file()


def test_hosted_oncall_contract_stays_incomplete(tmp_path: Path):
    evidence = run_hosted_oncall_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence.get("kind") == "contract_only"
    assert (tmp_path / "hosted_oncall_contract_drill.json").is_file()
