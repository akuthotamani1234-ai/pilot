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


def test_a_signed_in_principal_cannot_read_another_tenants_run(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.audit_store as audit_store
    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "tenancy.sqlite"
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "run-a").mkdir()
    (runs / "run-b").mkdir()
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setattr(audit_store, "DEFAULT_DB", db)
    monkeypatch.setattr(server, "RUNS", runs)
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("view-1", "t1", "v@ex.test", "viewer", db_path=db)
    tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://a.test", verdict="Ready", db_path=db)
    tenancy.index_run("run-b", "t2", source="https://b.test", verdict="Not Ready", db_path=db)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    missing = client.get("/api/report/run-a")
    assert missing.status_code == 401
    other = client.get("/api/report/run-a", headers={"Authorization": "Bearer admin-2"})
    assert other.status_code == 403
    unknown = client.get("/api/coverage/run-missing", headers={"Authorization": "Bearer view-1"})
    assert unknown.status_code == 403
    own = client.get("/api/v1/report/run-a", headers={"Authorization": "Bearer view-1"})
    assert own.status_code == 200
    assert own.json()["run"] == "run-a"
    stolen = client.get("/runs/run-a/report.html", headers={"Authorization": "Bearer admin-2"})
    assert stolen.status_code == 403


def test_the_run_list_hides_another_tenants_runs(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.audit_store as audit_store
    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "tenancy.sqlite"
    runs = tmp_path / "runs"
    for name, url in (("run-a", "https://a.test"), ("run-b", "https://b.test"), ("run-x", "https://x.test")):
        folder = runs / name
        folder.mkdir(parents=True)
        (folder / "summary.json").write_text(
            f'{{"url": "{url}", "verdict": "Ready"}}', encoding="utf-8")
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setattr(audit_store, "DEFAULT_DB", db)
    monkeypatch.setattr(server, "RUNS", runs)
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("view-1", "t1", "v@ex.test", "viewer", db_path=db)
    tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://a.test", verdict="Ready", db_path=db)
    tenancy.index_run("run-b", "t2", source="https://b.test", verdict="Not Ready", db_path=db)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    assert client.get("/api/history").status_code == 401
    own = client.get("/api/v1/history", headers={"Authorization": "Bearer view-1"})
    assert own.status_code == 200
    assert {row["run"] for row in own.json()} == {"run-a"}
    assert own.json()[0]["url"] == "https://a.test"
    other = client.get("/api/history", headers={"Authorization": "Bearer admin-2"})
    assert {row["run"] for row in other.json()} == {"run-b"}


def test_a_signed_in_principal_cannot_delete_another_tenants_run(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.audit_store as audit_store
    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "tenancy.sqlite"
    runs = tmp_path / "runs"
    (runs / "run-a").mkdir(parents=True)
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setattr(audit_store, "DEFAULT_DB", db)
    monkeypatch.setattr(server, "RUNS", runs)
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("view-1", "t1", "v@ex.test", "viewer", db_path=db)
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin", db_path=db)
    tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://a.test", verdict="Ready", db_path=db)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    header = {"X-Agentic-QA": "1"}
    stolen = client.delete("/api/runs/run-a", headers={**header, "Authorization": "Bearer admin-2"})
    assert stolen.status_code == 403
    assert (runs / "run-a").is_dir()
    viewer = client.delete("/api/runs/run-a", headers={**header, "Authorization": "Bearer view-1"})
    assert viewer.status_code == 403
    assert (runs / "run-a").is_dir()
    own = client.delete("/api/runs/run-a", headers={**header, "Authorization": "Bearer admin-1"})
    assert own.status_code == 200
    assert own.json()["removed"] == "run-a"
    assert not (runs / "run-a").is_dir()


def test_a_viewer_cannot_recheck_a_run(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.audit_store as audit_store
    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "tenancy.sqlite"
    runs = tmp_path / "runs"
    (runs / "run-a").mkdir(parents=True)
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setattr(audit_store, "DEFAULT_DB", db)
    monkeypatch.setattr(server, "RUNS", runs)
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("view-1", "t1", "v@ex.test", "viewer", db_path=db)
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin", db_path=db)
    tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://a.test", verdict="Ready", db_path=db)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    header = {"X-Agentic-QA": "1"}
    body = {"failure_ids": [1]}
    viewer = client.post("/api/runs/run-a/recheck", headers={**header, "Authorization": "Bearer view-1"}, json=body)
    assert viewer.status_code == 403
    other = client.post("/api/runs/run-a/recheck", headers={**header, "Authorization": "Bearer admin-2"}, json=body)
    assert other.status_code == 403
    owner = client.post("/api/runs/run-a/recheck", headers={**header, "Authorization": "Bearer admin-1"}, json=body)
    assert owner.status_code == 400
    assert "Nothing to re-check" in owner.json()["detail"]


def test_a_schedule_cannot_repeat_another_tenants_run(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.audit_store as audit_store
    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "tenancy.sqlite"
    runs = tmp_path / "runs"
    runs.mkdir()
    args = '{"source": "https://a.test/", "settings": {"llm_provider": "none", "environment": "test", "max_pages": 5}}'
    for name in ("run-a", "run-b"):
        folder = runs / name
        folder.mkdir()
        (folder / "run_args.json").write_text(args, encoding="utf-8")
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setattr(audit_store, "DEFAULT_DB", db)
    monkeypatch.setattr(server, "RUNS", runs)
    monkeypatch.setattr(server, "SCHEDULES", tmp_path / "schedules.json")
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("view-1", "t1", "v@ex.test", "viewer", db_path=db)
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin", db_path=db)
    tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://a.test", verdict="Ready", db_path=db)
    tenancy.index_run("run-b", "t2", source="https://b.test", verdict="Ready", db_path=db)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    header = {"X-Agentic-QA": "1"}
    body = {"run": "run-a", "every": "daily", "at": "07:00"}
    assert client.post("/api/schedules", headers={**header, "Authorization": "Bearer view-1"}, json=body).status_code == 403
    assert client.post("/api/schedules", headers={**header, "Authorization": "Bearer admin-2"}, json=body).status_code == 403
    created = client.post("/api/schedules", headers={**header, "Authorization": "Bearer admin-1"}, json=body)
    assert created.status_code == 200
    assert created.json()["from_run"] == "run-a"
    listed = client.get("/api/schedules", headers={"Authorization": "Bearer view-1"})
    assert [item["from_run"] for item in listed.json()] == ["run-a"]
    hidden = client.get("/api/schedules", headers={"Authorization": "Bearer admin-2"})
    assert hidden.json() == []
    sid = created.json()["id"]
    assert client.delete(f"/api/schedules/{sid}", headers={**header, "Authorization": "Bearer admin-2"}).status_code == 403
    assert client.delete(f"/api/schedules/{sid}", headers={**header, "Authorization": "Bearer view-1"}).status_code == 403
    removed = client.delete(f"/api/schedules/{sid}", headers={**header, "Authorization": "Bearer admin-1"})
    assert removed.status_code == 200 and removed.json()["deleted"] == 1


def test_a_signed_in_principal_cannot_stop_or_read_another_tenants_live_test(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import backend.audit_store as audit_store
    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "tenancy.sqlite"
    runs = tmp_path / "runs"
    (runs / "run-a").mkdir(parents=True)
    (runs / "run-a" / "review_request.json").write_text('{"questions": [{"id": "q1"}]}', encoding="utf-8")
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setattr(audit_store, "DEFAULT_DB", db)
    monkeypatch.setattr(server, "RUNS", runs)
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("view-1", "t1", "v@ex.test", "viewer", db_path=db)
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin", db_path=db)
    tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://a.test", verdict="Ready", db_path=db)
    tenancy.index_run("run-b", "t2", source="https://b.test", verdict="Ready", db_path=db)
    saved = dict(server.jobs)
    server.jobs.clear()
    try:
        proc = type("Proc", (), {"poll": lambda self: 0, "pid": 1})()
        server.jobs[1] = {"id": 1, "source": "https://a.test", "status": "running", "proc": proc,
                          "lines": ["secret log"], "pages": [], "stages": {}, "current": None,
                          "run": "run-a", "started": 1, "llm": {}, "secrets": [], "principal_id": "admin-1"}
        server.jobs[2] = {"id": 2, "source": "https://b.test", "status": "running", "proc": proc,
                          "lines": [], "pages": [], "stages": {}, "current": None,
                          "run": "run-b", "started": 2, "llm": {}, "secrets": [], "principal_id": "admin-2"}
        client = TestClient(server.app, base_url="http://127.0.0.1:8000")
        header = {"X-Agentic-QA": "1"}
        assert client.get("/api/runs/1", headers={"Authorization": "Bearer admin-2"}).status_code == 403
        assert client.get("/api/runs/1/events", headers={"Authorization": "Bearer admin-2"}).status_code == 403
        assert client.get("/api/runs/1/review", headers={"Authorization": "Bearer admin-2"}).status_code == 403
        assert client.post("/api/runs/1/stop", headers={**header, "Authorization": "Bearer admin-2"}).status_code == 403
        assert client.post("/api/runs/1/stop", headers={**header, "Authorization": "Bearer view-1"}).status_code == 403
        assert server.jobs[1]["status"] == "running"
        assert client.get("/api/runs/latest", headers={"Authorization": "Bearer admin-2"}).json()["id"] == 2
        seen = client.get("/api/runs/1/review", headers={"Authorization": "Bearer view-1"})
        assert seen.status_code == 200 and seen.json()["questions"][0]["id"] == "q1"
        stopped = client.post("/api/runs/1/stop", headers={**header, "Authorization": "Bearer admin-1"})
        assert stopped.status_code == 200
        assert server.jobs[1]["stopping"] is True
        reused = client.post(
            "/api/runs",
            headers={**header, "Authorization": "Bearer admin-1"},
            json={"source": "https://a.test", "authorized": True, "reuse_tests": True, "reuse_from_run": "run-b"},
        )
        assert reused.status_code == 403
        assert set(server.jobs) == {1, 2}
    finally:
        server.jobs.clear()
        server.jobs.update(saved)


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
