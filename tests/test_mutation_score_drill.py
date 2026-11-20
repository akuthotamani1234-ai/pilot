"""Gate J mutation score drill stays incomplete."""
from pathlib import Path

from backend.mutation_score_drill import run_mutation_score_drill


def test_mutation_score_drill_from_run7(tmp_path: Path):
    evidence = run_mutation_score_drill(ops_dir=tmp_path)
    assert evidence["gate_j_complete"] is False
    assert (tmp_path / "mutation_score_drill.json").is_file()
    assert evidence.get("ok") is True
    assert len((evidence.get("score") or {}).get("caught") or []) == 6
    assert (evidence.get("score") or {}).get("missed") == []
