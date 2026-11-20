"""Gate E DemoStore healing live drill stays incomplete."""
from pathlib import Path

from backend.demo_store_healing_live_drill import run_demo_store_healing_live_drill


def test_demo_store_healing_live_drill_reports_honestly(tmp_path: Path):
    evidence = run_demo_store_healing_live_drill(ops_dir=tmp_path)
    assert evidence["gate_e_complete"] is False
    assert (tmp_path / "demo_store_healing_live_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence["healing"]["locator_repair_allowed"] is True
    assert evidence["healing"]["weaken_denied"] is True
