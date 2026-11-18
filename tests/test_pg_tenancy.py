"""Gate G Postgres tenancy helpers when POSTGRES_URL is configured."""
import os

import pytest

from backend.pg_tenancy import (
    get_principal_pg,
    list_runs_for_tenant_pg,
    postgres_configured,
    runs_visible_to_principal_pg,
)
from backend.postgres_drill import isolation_drill


@pytest.mark.skipif(not postgres_configured() and not os.getenv("POSTGRES_URL"),
                    reason="POSTGRES_URL not configured")
def test_pg_tenancy_reads_isolation_drill_rows():
    drill = isolation_drill()
    assert drill.get("ok") is True
    principal = get_principal_pg("drill-pa")
    assert principal is not None
    assert principal["tenant_id"] == "drill-a"
    assert principal["role"] == "admin"
    runs = list_runs_for_tenant_pg("drill-a")
    assert any(r["run_id"] == "drill-run-a" for r in runs)
    assert not any(r["run_id"] == "drill-run-b" for r in runs)
    visible = runs_visible_to_principal_pg("drill-pa")
    assert visible["ok"] is True
    assert visible["backend"] == "postgres"
    assert visible["gate_g_complete"] is False
    assert any(r["run_id"] == "drill-run-a" for r in visible["runs"])
