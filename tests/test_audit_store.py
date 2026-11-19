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


def test_a_linked_run_does_not_open_another_tenants_report(monkeypatch, tmp_path):
    import json

    from fastapi.testclient import TestClient

    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "tenancy.sqlite"
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    runs = server.RUNS
    name_a = "zz_link_a_20260101_000000"
    name_b = "zz_link_b_20260101_000000"
    name_c = "zz_link_c_20260101_000000"
    secret = "tenant-a-only-finding"
    folder_a, folder_b, folder_c = runs / name_a, runs / name_b, runs / name_c
    try:
        folder_a.mkdir()
        (folder_a / "report.html").write_text(f"<p>{secret}</p>", encoding="utf-8")
        (folder_a / "summary.json").write_text(
            json.dumps({"url": "https://a.test", "verdict": "Ready", "note": secret}), encoding="utf-8")
        folder_b.symlink_to(folder_a, target_is_directory=True)
        folder_c.mkdir()
        (folder_c / "summary.json").symlink_to(folder_a / "summary.json")
        (folder_c / "report.html").symlink_to(folder_a / "report.html")
        tenancy.upsert_tenant("t1", "One", db_path=db)
        tenancy.upsert_tenant("t2", "Two", db_path=db)
        tenancy.upsert_principal("view-1", "t1", "v@ex.test", "viewer", db_path=db)
        tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin", db_path=db)
        tenancy.index_run(name_a, "t1", source="https://a.test", verdict="Ready", db_path=db)
        tenancy.index_run(name_b, "t2", source="https://b.test", verdict="Ready", db_path=db)
        tenancy.index_run(name_c, "t2", source="https://c.test", verdict="Ready", db_path=db)
        client = TestClient(server.app, base_url="http://127.0.0.1:8000")
        other = {"Authorization": "Bearer admin-2"}
        owner = {"Authorization": "Bearer view-1"}
        linked = client.get(f"/api/report/{name_b}", headers=other)
        assert linked.status_code == 400
        assert secret not in linked.text
        page = client.get(f"/runs/{name_b}/report.html", headers=other)
        assert page.status_code == 404
        assert secret not in page.text
        copied = client.get(f"/api/report/{name_c}", headers=other)
        assert copied.status_code == 200
        assert secret not in copied.text
        assert copied.json()["summary"] is None
        copied_page = client.get(f"/runs/{name_c}/report.html", headers=other)
        assert copied_page.status_code == 404
        assert secret not in copied_page.text
        own = client.get(f"/api/report/{name_a}", headers=owner)
        assert own.status_code == 200
        assert secret in own.text
        own_page = client.get(f"/runs/{name_a}/report.html", headers=owner)
        assert own_page.status_code == 200
        assert secret in own_page.text
        listed = client.get("/api/history", headers=other)
        assert listed.status_code == 200
        assert secret not in listed.text
        assert name_b not in {row["run"] for row in listed.json()}
    finally:
        if folder_b.is_symlink():
            folder_b.unlink()
        for folder in (folder_a, folder_c):
            if folder.exists() and not folder.is_symlink():
                import shutil
                shutil.rmtree(folder, ignore_errors=True)


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


def test_a_tenants_saved_tests_stay_off_another_tenants_website(monkeypatch, tmp_path):
    import requests
    from fastapi.testclient import TestClient

    import backend.tenancy_store as tenancy
    from backend import my_tests, server
    from backend.agents.change_detection import baseline_path
    from backend.config import settings

    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    monkeypatch.delenv("QPILOT_TENANT_ID", raising=False)
    saved = my_tests.save("shop.test", ["See the shop heading"], tenant_id="t1")
    assert [item["text"] for item in saved] == ["See the shop heading"]
    assert my_tests.load("shop.test") == []
    assert my_tests.load("shop.test", tenant_id="t2") == []
    monkeypatch.setenv("QPILOT_TENANT_ID", "t1")
    assert baseline_path("shop.test") == tmp_path / "baseline" / "t1" / "shop.test"
    assert [item["text"] for item in my_tests.load("shop.test")] == ["See the shop heading"]

    db = tmp_path / "tenancy.sqlite"
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin", db_path=db)
    tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin", db_path=db)

    def fake_get(url, **_kwargs):
        class Raw:
            def read(self, _n, decode_content=True):
                return b"<html><title>Shop</title></html>"

        class Response:
            status_code = 200
            is_redirect = False
            headers: dict = {}
            raw = Raw()

            def __init__(self):
                self.url = url
                self.text = "<html><title>Shop</title></html>"

            def close(self):
                return None

        return Response()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(server, "is_private_host", lambda *_args, **_kwargs: False)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    own = client.get("/api/check", params={"source": "https://shop.test"}, headers={"Authorization": "Bearer admin-1"})
    other = client.get("/api/check", params={"source": "https://shop.test"}, headers={"Authorization": "Bearer admin-2"})
    assert own.status_code == 200 and own.json()["my_tests"] == ["See the shop heading"]
    assert other.status_code == 200 and other.json()["my_tests"] == []
    env: dict = {}
    server._stamp_tenant_env(env, "admin-2")
    assert env["QPILOT_TENANT_ID"] == "t2"
    server._stamp_tenant_env(env, "")
    assert "QPILOT_TENANT_ID" not in env


def test_a_scheduled_run_and_an_approved_look_stay_in_that_tenants_baseline(monkeypatch, tmp_path):
    import json
    from datetime import datetime

    from fastapi.testclient import TestClient

    import backend.tenancy_store as tenancy
    from backend import my_tests, server
    from backend.config import settings

    db = tmp_path / "tenancy.sqlite"
    runs = tmp_path / "runs"
    run = runs / "run-a"
    run.mkdir(parents=True)
    (run / "run_args.json").write_text(
        '{"source": "https://shop.test/", "site_key": "shop.test", "settings": {"llm_provider": "none", "environment": "test"}}',
        encoding="utf-8")
    (run / "shot.png").write_bytes(b"png")
    (run / "cap.json").write_text('{"url": "https://shop.test/", "desktop": {"shot": "shot.png"}}', encoding="utf-8")
    (run / "visual.json").write_text(
        '{"pages": [{"status": "changed", "key": "home", "title": "Home", "capture": "cap.json"}],'
        ' "counts": {"changed": 1, "approved": 0}}',
        encoding="utf-8")
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.delenv("QPILOT_TENANT_ID", raising=False)
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    monkeypatch.setattr(tenancy, "DEFAULT_DB", db)
    monkeypatch.setattr(server, "RUNS", runs)
    monkeypatch.setattr(server, "SCHEDULES", tmp_path / "schedules.json")
    tenancy.upsert_tenant("t1", "One", db_path=db)
    tenancy.upsert_tenant("t2", "Two", db_path=db)
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin", db_path=db)
    tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin", db_path=db)
    tenancy.index_run("run-a", "t1", source="https://shop.test", verdict="Ready", db_path=db)
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    header = {"X-Agentic-QA": "1"}
    created = client.post(
        "/api/schedules", headers={**header, "Authorization": "Bearer admin-1"},
        json={"run": "run-a", "every": "daily", "at": "07:00"},
    )
    assert created.status_code == 200 and created.json()["tenant_id"] == "t1"
    saved = json.loads((tmp_path / "schedules.json").read_text(encoding="utf-8"))
    saved[0]["next"] = "2020-01-01T00:00"
    (tmp_path / "schedules.json").write_text(json.dumps(saved), encoding="utf-8")
    seen = []

    def fake_start(_req):
        seen.append(my_tests.baseline_folder("shop.test"))
        return {"id": 7}

    monkeypatch.setattr(server, "start_run", fake_start)
    assert server.run_due_schedules(datetime(2020, 1, 1, 0, 10)) == [created.json()["id"]]
    assert seen == [tmp_path / "baseline" / "t1" / "shop.test"]
    assert my_tests.current_baseline_tenant() == ""

    other = client.post(
        "/api/visual/run-a/approve", headers={**header, "Authorization": "Bearer admin-2"}, json={},
    )
    assert other.status_code == 403
    approved = client.post(
        "/api/visual/run-a/approve", headers={**header, "Authorization": "Bearer admin-1"}, json={},
    )
    assert approved.status_code == 200 and approved.json()["approved"] == 1
    assert (tmp_path / "baseline" / "t1" / "shop.test" / "visual" / "index.json").is_file()
    assert not (tmp_path / "baseline" / "shop.test").exists()
    assert my_tests.current_baseline_tenant() == ""


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
