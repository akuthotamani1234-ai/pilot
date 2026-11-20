"""Gate H multi-store DR stays incomplete."""
import os
from pathlib import Path

import pytest

from backend.multi_store_dr_drill import run_multi_store_dr_drill


@pytest.mark.skipif(
    not (
        (os.getenv("POSTGRES_URL") or os.getenv("QPILOT_DB_URL"))
        and (os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL"))
        and (os.getenv("OBJECT_STORE_URI") or os.getenv("MINIO_URL"))
    ),
    reason="Postgres/Redis/MinIO not all configured",
)
def test_multi_store_dr_drill_all_three(tmp_path: Path):
    evidence = run_multi_store_dr_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert (tmp_path / "multi_store_dr_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("passed") == 3
