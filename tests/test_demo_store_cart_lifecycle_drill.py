"""Gate C DemoStore cart lifecycle drill stays incomplete and empties cart."""
from pathlib import Path

from backend.demo_store_cart_lifecycle_drill import run_demo_store_cart_lifecycle_drill


def test_demo_store_cart_lifecycle_drill_empties_cart(tmp_path: Path):
    evidence = run_demo_store_cart_lifecycle_drill(ops_dir=tmp_path)
    assert evidence["gate_c_complete"] is False
    assert evidence["ok"] is True
    assert evidence["confirmed"] >= 1
    assert evidence["failed"] == 0
    assert evidence["cart_empty"] is True
    assert (tmp_path / "demo_store_cart_lifecycle_drill.json").is_file()
