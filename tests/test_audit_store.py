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
