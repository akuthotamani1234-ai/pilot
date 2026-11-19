"""Gate G offline SQLite tenancy tables + isolation helper."""
from pathlib import Path

from backend.audit_store import list_audits
from backend.tenancy_store import (
    assert_run_access,
    can_read_run,
    get_principal,
    get_run_tenant,
    index_run,
    list_runs_for_tenant,
    runs_visible_to_principal,
    upsert_principal,
    upsert_tenant,
)


def test_a_second_write_cannot_move_or_raise_a_principal(tmp_path: Path):
    db = tmp_path / "tenancy.sqlite"
    upsert_tenant("t-a", "A", db_path=db)
    upsert_tenant("t-b", "B", db_path=db)
    upsert_principal("p-a", "t-a", "a@ex.test", "viewer", db_path=db)
    moved = upsert_principal("p-a", "t-b", "a@ex.test", "admin", db_path=db)
    assert moved["ok"] is False and moved["tenant_id"] == "t-a" and moved["role"] == "viewer"
    raised = upsert_principal("p-a", "t-a", "a@ex.test", "admin", db_path=db)
    assert raised["ok"] is False
    assert get_principal("p-a", db_path=db)["role"] == "viewer"
    mail = upsert_principal("p-a", "t-a", "new@ex.test", "viewer", db_path=db)
    assert mail["ok"] is True
    assert get_principal("p-a", db_path=db)["email"] == "new@ex.test"


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
    stolen = index_run("run-a", "t-b", source="https://b.test", verdict="Not Ready", db_path=db)
    assert stolen["ok"] is False and stolen["tenant_id"] == "t-a"
    assert [r["run_id"] for r in list_runs_for_tenant("t-a", db_path=db)] == ["run-a"]
    assert list_runs_for_tenant("t-b", db_path=db)[0]["run_id"] == "run-b"
    refreshed = index_run("run-a", "t-a", source="https://a.test", verdict="Ready with Risks", db_path=db)
    assert refreshed["ok"] is True
    assert list_runs_for_tenant("t-a", db_path=db)[0]["verdict"] == "Ready with Risks"


def test_a_tenant_database_does_not_follow_a_link_into_another_file(tmp_path, monkeypatch):
    import json

    import pytest

    from backend import server
    from backend.approvals import create, list_approvals
    from backend.audit_store import list_audits, record_audit

    secret = b"tenant-b-only-db"
    other = tmp_path / "other"
    other.mkdir()
    tenant_db = other / "tenancy.sqlite"
    audit_db = other / "audit.sqlite"
    approval_db = other / "approvals.sqlite"
    schedule = other / "schedules.json"
    for path in (tenant_db, audit_db, approval_db):
        path.write_bytes(secret)
    schedule.write_text(json.dumps([{"secret": "tenant-b-only-db"}]), encoding="utf-8")

    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError):
        upsert_tenant("t-a", "A", db_path=linked / "tenancy.sqlite")
    with pytest.raises(ValueError):
        record_audit(actor="p-a", action="run.read", allowed=False, db_path=linked / "audit.sqlite")
    with pytest.raises(ValueError):
        create("heal", "fix", path=linked / "approvals.sqlite")
    assert list_runs_for_tenant("t-a", db_path=linked / "tenancy.sqlite") == []
    assert list_audits(db_path=linked / "audit.sqlite") == []
    assert list_approvals(path=linked / "approvals.sqlite") == []

    real = tmp_path / "real"
    real.mkdir()
    (real / "tenancy.sqlite").symlink_to(tenant_db)
    (real / "audit.sqlite").symlink_to(audit_db)
    (real / "approvals.sqlite").symlink_to(approval_db)
    (real / "schedules.json").symlink_to(schedule)
    with pytest.raises(ValueError):
        index_run("run-a", "t-a", source="https://a.test", verdict="Ready", db_path=real / "tenancy.sqlite")
    with pytest.raises(ValueError):
        record_audit(actor="p-a", action="run.read", allowed=True, db_path=real / "audit.sqlite")
    with pytest.raises(ValueError):
        create("heal", "fix", path=real / "approvals.sqlite")
    assert get_principal("p-a", db_path=real / "tenancy.sqlite") is None
    assert get_run_tenant("run-a", db_path=real / "tenancy.sqlite") is None
    monkeypatch.setattr(server, "SCHEDULES", real / "schedules.json")
    assert server._schedules() == []
    assert server._save_schedules([{"id": "S1", "source": "https://shop.example"}]) is False
    for path in (tenant_db, audit_db, approval_db):
        assert path.read_bytes() == secret
    assert json.loads(schedule.read_text(encoding="utf-8"))[0]["secret"] == "tenant-b-only-db"

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    upsert_tenant("t-a", "A", db_path=fresh / "tenancy.sqlite")
    index_run("run-a", "t-a", source="https://a.test", verdict="Ready", db_path=fresh / "tenancy.sqlite")
    assert [row["run_id"] for row in list_runs_for_tenant("t-a", db_path=fresh / "tenancy.sqlite")] == ["run-a"]
    saved = record_audit(actor="p-a", action="run.read", allowed=True, db_path=fresh / "audit.sqlite")
    assert saved["persisted"] is True
    assert list_audits(db_path=fresh / "audit.sqlite")[0]["action"] == "run.read"
    row = create("heal", "fix the button", path=fresh / "approvals.sqlite")
    assert row["kind"] == "heal"
    assert list_approvals(path=fresh / "approvals.sqlite")[0]["id"] == row["id"]
    monkeypatch.setattr(server, "SCHEDULES", fresh / "schedules.json")
    assert server._save_schedules([{"id": "S1", "source": "https://shop.example"}]) is True
    assert json.loads((fresh / "schedules.json").read_text(encoding="utf-8"))[0]["id"] == "S1"
    assert b"tenant-b-only-db" not in (fresh / "tenancy.sqlite").read_bytes()
