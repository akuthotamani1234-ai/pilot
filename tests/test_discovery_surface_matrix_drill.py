from pathlib import Path

from backend.discovery_surface_matrix_drill import run_discovery_surface_matrix_drill


def test_discovery_surface_matrix_reports_honestly(tmp_path: Path):
    evidence = run_discovery_surface_matrix_drill(ops_dir=tmp_path)
    assert evidence["gate_a_complete"] is False
    assert (tmp_path / "discovery_surface_matrix_drill.json").is_file()
    assert evidence.get("total") == 4
    assert isinstance(evidence.get("ok"), bool)
    assert evidence.get("union_of") == 11
