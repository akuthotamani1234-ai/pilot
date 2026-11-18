"""Gate D combined device matrix drill stays incomplete."""
from pathlib import Path

from backend.device_matrix_drill import run_device_matrix_drill


def test_device_matrix_drill_includes_android_dry_run(tmp_path: Path):
    evidence = run_device_matrix_drill(ops_dir=tmp_path)
    assert evidence["gate_d_complete"] is False
    assert evidence["android_dry_run_rows"] >= 1
    assert evidence["adb_probe"]["adb_present"] is True
    assert evidence["ok"] is True
    assert (tmp_path / "device_matrix_drill.json").is_file()
