"""Gate G offline SQLite tenancy tables + isolation helper."""
from pathlib import Path

from backend.tenancy_store import (
    can_read_run,
    index_run,
    list_runs_for_tenant,
    upsert_principal,
    upsert_tenant,
)


def test_tenancy_crud_and_isolation(tmp_path: Path):
    db = tmp_path / "tenancy.sqlite"
    upsert_tenant("t-a", "A", db_path=db)
    upsert_tenant("t-b", "B", db_path=db)
    upsert_principal("p-a", "t-a", "a@ex.test", "operator", db_path=db)
    index_run("run-a", "t-a", source="https://a.test", verdict="Ready", db_path=db)
    index_run("run-b", "t-b", source="https://b.test", verdict="Not Ready", db_path=db)
    assert [r["run_id"] for r in list_runs_for_tenant("t-a", db_path=db)] == ["run-a"]
    assert can_read_run(role="operator", actor_tenant="t-a", run_tenant="t-a") is True
    assert can_read_run(role="operator", actor_tenant="t-a", run_tenant="t-b") is False
    assert can_read_run(role="admin", actor_tenant="t-a", run_tenant="t-b") is False  # still tenant-isolated
