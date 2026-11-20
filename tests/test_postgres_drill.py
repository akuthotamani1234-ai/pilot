"""Gate G Postgres isolation drill (skips when POSTGRES_URL unset or psql fails)."""
import os
import shutil

import pytest

from backend.postgres_drill import isolation_drill


@pytest.mark.skipif(shutil.which("psql") is None, reason="psql missing")
def test_postgres_isolation_drill_when_configured(monkeypatch):
    dsn = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL") or ""
    if not dsn:
        # Local cloud agent default used for live drills on this machine.
        dsn = "postgresql://qpilot:qpilot@127.0.0.1:5432/qpilot"
        monkeypatch.setenv("POSTGRES_URL", dsn)
    evidence = isolation_drill(dsn=dsn)
    if not evidence.get("ok"):
        pytest.skip(evidence.get("reason") or "postgres unavailable")
    assert evidence["gate_g_complete"] is False
    assert evidence["tenant_a_runs"] == ["drill-run-a"]
    assert evidence["cross_tenant_hits"] == "0"
