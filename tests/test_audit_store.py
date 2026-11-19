"""Gate G: RBAC audit events persist into the migrated SQLite schema."""
from backend.audit_store import export_audits, list_audits, record_audit


def test_record_and_list_audit_events(tmp_path):
    db = tmp_path / "audit.sqlite"
    event = record_audit(actor="op", action="run.write", allowed=True, tenant_id="t1",
                         detail="started run", db_path=db)
    assert event["persisted"] is True
    rows = list_audits(db_path=db)
    assert len(rows) == 1
    assert rows[0]["actor"] == "op"
    assert rows[0]["action"] == "run.write"
    assert rows[0]["allowed"] is True


def test_a_signed_in_principal_sees_only_their_own_audit_events(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.audit_store as audit_store
    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "audit.sqlite"
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(audit_store, "DEFAULT_DB", db)
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin", db_path=db)
    tenancy.upsert_principal("view-1", "t1", "v@ex.test", "viewer", db_path=db)
    audit_store.record_audit(actor="admin-1", action="run.read", allowed=True, tenant_id="t1", db_path=db)
    audit_store.record_audit(actor="other", action="run.read", allowed=False, tenant_id="t2", db_path=db)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    missing = client.get("/api/audit/events")
    assert missing.status_code == 401
    viewer = client.get("/api/audit/events", headers={"Authorization": "Bearer view-1"})
    assert viewer.status_code == 403
    other = client.get("/api/audit/events", headers={"Authorization": "Bearer admin-1"}, params={"tenant_id": "t2"})
    assert other.status_code == 403
    own = client.get("/api/audit/export", headers={"Authorization": "Bearer admin-1"})
    assert own.status_code == 200
    body = own.json()
    assert body["tenant_id"] == "t1"
    assert [event["actor"] for event in body["events"]] == ["admin-1"]
    assert body["gate_g_complete"] is False


def test_tenant_scoped_list_and_export(tmp_path):
    db = tmp_path / "audit.sqlite"
    record_audit(actor="a", action="run.read", allowed=True, tenant_id="t1", db_path=db)
    record_audit(actor="b", action="run.read", allowed=False, tenant_id="t2", db_path=db)
    scoped = list_audits(tenant_id="t1", db_path=db)
    assert len(scoped) == 1
    assert scoped[0]["tenant_id"] == "t1"
    exported = export_audits(tenant_id="t2", db_path=db)
    assert exported["gate_g_complete"] is False
    assert exported["count"] == 1
    assert exported["events"][0]["actor"] == "b"
