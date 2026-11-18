"""Gate E controlled failure matrix stays incomplete and covers key categories."""
from pathlib import Path

from backend.failure_matrix import build_failure_matrix, run_failure_matrix_drill


def test_failure_matrix_covers_taxonomy(tmp_path: Path):
    matrix = build_failure_matrix()
    assert matrix["gate_e_complete"] is False
    assert matrix["cases"] >= 6
    cats = set(matrix["counts"])
    # Core buckets we expect from the fixture set.
    assert "product_defect" in cats or "test_defect" in cats
    assert "flaky" in cats
    evidence = run_failure_matrix_drill(ops_dir=tmp_path)
    assert (tmp_path / "failure_matrix_drill.json").is_file()
    assert evidence["counts"] == matrix["counts"]
