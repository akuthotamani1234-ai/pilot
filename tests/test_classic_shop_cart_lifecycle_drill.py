from pathlib import Path

from backend.classic_shop_cart_lifecycle_drill import (
    run_classic_shop_cart_lifecycle_drill,
)


def test_classic_shop_cart_lifecycle_reports_honestly(tmp_path: Path):
    evidence = run_classic_shop_cart_lifecycle_drill(ops_dir=tmp_path)
    assert evidence["gate_c_complete"] is False
    assert (tmp_path / "classic_shop_cart_lifecycle_drill.json").is_file()
    assert evidence.get("ok") is True
