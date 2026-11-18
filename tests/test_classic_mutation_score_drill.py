from pathlib import Path

from backend.classic_mutation_score_drill import run_classic_mutation_score_drill


def test_classic_mutation_score_reports_honestly(tmp_path: Path):
    evidence = run_classic_mutation_score_drill(ops_dir=tmp_path)
    assert evidence["gate_j_complete"] is False
    assert (tmp_path / "classic_mutation_score_drill.json").is_file()
    assert evidence.get("ok") is True
    assert len((evidence.get("score") or {}).get("caught") or []) == 3
