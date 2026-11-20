"""QX capability bundle stays incomplete; all offline checks must pass."""
from pathlib import Path

from backend.qx_capabilities_drill import run_qx_capabilities_drill


def test_qx_capabilities_drill_reports_honestly(tmp_path: Path):
    evidence = run_qx_capabilities_drill(ops_dir=tmp_path)
    assert evidence["gate_complete"] is False
    assert (tmp_path / "qx_capabilities_drill.json").is_file()
    assert evidence.get("ok") is True
    assert all(evidence.get("checks") or {}.values())
