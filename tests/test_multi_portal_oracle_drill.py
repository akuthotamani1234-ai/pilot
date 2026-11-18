from pathlib import Path

from backend.multi_portal_oracle_drill import run_multi_portal_oracle_drill


def test_multi_portal_oracle_drill_reports_honestly(tmp_path: Path):
    evidence = run_multi_portal_oracle_drill(ops_dir=tmp_path)
    assert evidence["gate_c_complete"] is False
    assert (tmp_path / "multi_portal_oracle_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("passed") == evidence.get("total") == 4
