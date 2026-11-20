"""Gate H multi-region DR stays incomplete; skips when POSTGRES_URL unset."""
import os
from pathlib import Path

import pytest

from backend.multi_region_dr_drill import run_multi_region_dr_drill


@pytest.mark.skipif(
    not (os.getenv("POSTGRES_URL") or os.getenv("QPILOT_DB_URL")),
    reason="POSTGRES_URL not configured",
)
def test_multi_region_dr_drill_failsover(tmp_path: Path):
    evidence = run_multi_region_dr_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert (tmp_path / "multi_region_dr_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("region_a") == "qpilot_region_a"
    assert evidence.get("region_b") == "qpilot_region_b"
