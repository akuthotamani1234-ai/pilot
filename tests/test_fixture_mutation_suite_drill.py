from pathlib import Path

from backend.fixture_mutation_suite_drill import run_fixture_mutation_suite_drill


def test_fixture_mutation_suite_reports_honestly(tmp_path: Path):
    evidence = run_fixture_mutation_suite_drill(ops_dir=tmp_path)
    assert evidence["gate_j_complete"] is False
    assert (tmp_path / "fixture_mutation_suite_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("passed") == evidence.get("total") == 2
