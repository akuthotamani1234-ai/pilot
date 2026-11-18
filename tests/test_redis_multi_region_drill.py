"""Gate H Redis dual-DB failover stays incomplete."""
import os
from pathlib import Path

import pytest

from backend.redis_multi_region_drill import run_redis_multi_region_drill


@pytest.mark.skipif(
    not (os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL")),
    reason="REDIS_URL not configured",
)
def test_redis_multi_region_drill_failsover(tmp_path: Path):
    evidence = run_redis_multi_region_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert evidence["gate_b_complete"] is False
    assert (tmp_path / "redis_multi_region_drill.json").is_file()
    assert evidence.get("ok") is True
