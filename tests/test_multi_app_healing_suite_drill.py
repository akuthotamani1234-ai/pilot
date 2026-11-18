from pathlib import Path

from backend.multi_app_healing_suite_drill import run_multi_app_healing_suite_drill


def test_multi_app_healing_suite_reports_honestly(tmp_path: Path):
    evidence = run_multi_app_healing_suite_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert (tmp_path / "multi_app_healing_suite_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("passed") == evidence.get("total") == 4
