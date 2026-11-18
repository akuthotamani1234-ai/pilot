"""Gate D multi-API Android matrix stays incomplete."""
from pathlib import Path

from backend.multi_api_android_matrix_drill import run_multi_api_android_matrix_drill


def test_multi_api_android_matrix_drill_reports_honestly(tmp_path: Path):
    evidence = run_multi_api_android_matrix_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert (tmp_path / "multi_api_android_matrix_drill.json").is_file()
    # ok only when both smoke + appium evidence files are present and green.
    if evidence.get("ok"):
        assert 24 in (evidence.get("api_levels") or [])
        assert any(a >= 26 for a in (evidence.get("api_levels") or []))
    else:
        assert evidence.get("reason")
