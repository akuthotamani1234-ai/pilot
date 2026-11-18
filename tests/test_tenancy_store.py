"""Gate G offline SQLite tenancy tables + isolation helper."""
from pathlib import Path

from backend.audit_store import list_audits
from backend.tenancy_store import (
    assert_run_access,
    can_read_run,
    get_principal,
    index_run,
    list_runs_for_tenant,
    runs_visible_to_principal,
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
    assert get_principal("p-a", db_path=db)["tenant_id"] == "t-a"
    visible = runs_visible_to_principal("p-a", db_path=db)
    assert visible["ok"] is True
    assert [r["run_id"] for r in visible["runs"]] == ["run-a"]
    assert visible["gate_g_complete"] is False
    denied = assert_run_access(principal_id="p-a", run_id="run-b", db_path=db)
    assert denied["allowed"] is False
    audits = list_audits(limit=5, db_path=db)
    assert any(a["action"] == "run.read" and not a["allowed"] for a in audits)
    allowed = assert_run_access(principal_id="p-a", run_id="run-a", db_path=db)
    assert allowed["allowed"] is True
