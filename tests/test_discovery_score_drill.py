from pathlib import Path

from backend.discovery_score_drill import run_discovery_score_drill


def test_discovery_score_drill_reports_honestly(tmp_path: Path):
    evidence = run_discovery_score_drill(ops_dir=tmp_path)
    assert evidence["gate_a_complete"] is False
    assert (tmp_path / "discovery_score_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("passed") == evidence.get("total") == 4
