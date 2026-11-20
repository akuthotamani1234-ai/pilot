"""Gate E offline healing regression suite stays incomplete and self-consistent."""
from pathlib import Path

from backend.healing_regression import build_healing_regression, run_healing_regression_drill


def test_healing_regression_matches_expectations(tmp_path: Path):
    matrix = build_healing_regression()
    assert matrix["gate_e_complete"] is False
    assert matrix["cases"] >= 4
    assert matrix["mismatches"] == 0
    assert matrix["policy"] == "locator_only"
    evidence = run_healing_regression_drill(ops_dir=tmp_path)
    assert (tmp_path / "healing_regression_drill.json").is_file()
    assert evidence["mismatches"] == 0
