"""Gate H Postgres DR stays incomplete; skips when POSTGRES_URL unset."""
import os
from pathlib import Path

import pytest

from backend.postgres_dr_drill import run_postgres_dr_drill


@pytest.mark.skipif(
    not (os.getenv("POSTGRES_URL") or os.getenv("QPILOT_DB_URL")),
    reason="POSTGRES_URL not configured",
)
def test_postgres_dr_drill_restores_isolated(tmp_path: Path):
    evidence = run_postgres_dr_drill(ops_dir=tmp_path)
    assert evidence["gate_h_complete"] is False
    assert (tmp_path / "postgres_dr_drill.json").is_file()
    assert evidence.get("ok") is True
    assert evidence.get("isolated_db") == "qpilot_dr_restore"
