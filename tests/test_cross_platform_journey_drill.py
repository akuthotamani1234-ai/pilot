"""QX-A10 cross-platform journey stays incomplete."""
from pathlib import Path

from backend.cross_platform_journey_drill import run_cross_platform_journey_drill


def test_cross_platform_journey_drill_reports_honestly(tmp_path: Path):
    evidence = run_cross_platform_journey_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["gate_f_complete"] is False
    assert (tmp_path / "cross_platform_journey_drill.json").is_file()
    assert evidence.get("ok") is True
    assert len([s for s in (evidence.get("surfaces") or []) if s.startswith("web.")]) >= 2
    assert (evidence.get("web_compare") or {}).get("status") == "matched"
