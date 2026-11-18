from pathlib import Path

from backend.production_healing_matrix_drill import run_production_healing_matrix_drill


def test_production_healing_matrix_reports_honestly(tmp_path: Path):
    evidence = run_production_healing_matrix_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert (tmp_path / "production_healing_matrix_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("passed") == evidence.get("total") == 2
