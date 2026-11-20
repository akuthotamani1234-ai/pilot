from pathlib import Path

from backend.production_healing_contract_drill import (
    run_production_healing_contract_drill,
)


def test_production_healing_contract_stays_incomplete(tmp_path: Path):
    evidence = run_production_healing_contract_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert evidence.get("kind") == "contract_only"
    assert (tmp_path / "production_healing_contract_drill.json").is_file()
