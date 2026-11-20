"""Gate I SSO contract drill stays incomplete and never claims ready."""
from pathlib import Path

from backend.sso_contract_drill import run_sso_contract_drill


def test_sso_contract_drill_never_ready(tmp_path: Path):
    evidence = run_sso_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_i_complete"] is False
    assert evidence["ready"] is False
    assert evidence["ok"] is True
    assert evidence["jwt_helper"]
    assert (tmp_path / "sso_contract_drill.json").is_file()
