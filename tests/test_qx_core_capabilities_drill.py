"""QX core capability bundle stays incomplete; offline checks must pass."""
from pathlib import Path

from backend.qx_core_capabilities_drill import run_qx_core_capabilities_drill


def test_qx_core_capabilities_drill_reports_honestly(tmp_path: Path):
    evidence = run_qx_core_capabilities_drill(ops_dir=tmp_path)
    assert evidence["gate_complete"] is False
    assert (tmp_path / "qx_core_capabilities_drill.json").is_file()
    assert evidence.get("ok") is True
    assert all((evidence.get("checks") or {}).values())
