from pathlib import Path

from backend.apidemos_interaction_drill import run_apidemos_interaction_drill


def test_apidemos_interaction_reports_honestly(tmp_path: Path):
    evidence = run_apidemos_interaction_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert (tmp_path / "apidemos_interaction_drill.json").is_file()
    assert isinstance(evidence.get("ok"), bool)
