"""Gate H MinIO dual-bucket failover stays incomplete."""
import os
from pathlib import Path

import pytest

from backend.minio_multi_region_drill import run_minio_multi_region_drill


@pytest.mark.skipif(
    not (os.getenv("OBJECT_STORE_URI") or os.getenv("MINIO_URL")),
    reason="OBJECT_STORE_URI / MINIO_URL not configured",
)
def test_minio_multi_region_drill_failsover(tmp_path: Path):
    evidence = run_minio_multi_region_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert (tmp_path / "minio_multi_region_drill.json").is_file()
    if evidence.get("open_a", {}).get("ready") and evidence.get("open_b", {}).get("ready"):
        assert evidence.get("ok") is True
