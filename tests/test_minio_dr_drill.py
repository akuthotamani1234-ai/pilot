"""Gate H MinIO backup/restore drill stays incomplete and records evidence when MinIO is up."""
import os
from pathlib import Path

import pytest

from backend.minio_dr_drill import object_store_backup_restore_drill


@pytest.mark.skipif(
    not (os.getenv("OBJECT_STORE_URI") or os.getenv("MINIO_URL")),
    reason="OBJECT_STORE_URI / MinIO not configured in this environment",
)
def test_minio_backup_restore_drill_when_configured(tmp_path: Path, monkeypatch):
    # Keep writing primary evidence paths; drill always targets docs/ops-evidence.
    evidence = object_store_backup_restore_drill()
    assert evidence["gate_h_complete"] is False
    assert evidence["gate_g_complete"] is False
    if evidence.get("open", {}).get("ready"):
        assert evidence["ok"] is True
        assert evidence["drill"] == "minio_object_backup_restore"
