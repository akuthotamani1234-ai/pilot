"""Gate I: durable approvals queue uses human_review.decide."""
import json
from pathlib import Path

import pytest

from backend.approvals import create, decide_approval, list_approvals, snapshot
from backend.healing_policy import reset_healing_approvals

_OLD = (
    'def test_x(page):\n'
    '    page.locator("#a").click()\n'
    '    assert page.locator("#ok").is_visible()\n'
)
_GOOD = (
    'def test_x(page):\n'
    '    page.locator("#b").click()\n'
    '    assert page.locator("#ok").is_visible()\n'
)
_BAD = (
    'def test_x(page):\n'
    '    page.locator("#a").click()\n'
    '    assert True\n'
)


def _detail(new_code: str, failure_class: str) -> str:
    return json.dumps({
        "old_code": _OLD,
        "new_code": new_code,
        "failure_class": failure_class,
    })


def test_create_list_and_decide(tmp_path: Path):
    db = tmp_path / "approvals.sqlite"
    row = create(
        "heal", "locator #buy", detail=_detail(_GOOD, "locator"), path=db,
    )
    assert row["status"] == "pending"
    pending = list_approvals(status="pending", path=db)
    assert len(pending) == 1
    accepted = decide_approval(row["id"], "yes", path=db)
    assert accepted["status"] == "accepted"
    assert accepted["reason"] == "a person accepted it"
    assert list_approvals(status="pending", path=db) == []
    snap = snapshot(path=db)
    assert snap["gate_i_complete"] is False
    assert snap["gate_i_approvals_ready"] is True


def test_no_answer_keeps_safe_reject(tmp_path: Path):
    db = tmp_path / "approvals.sqlite"
    row = create("sensitive", "delete account", path=db)
    out = decide_approval(row["id"], "", path=db)
    assert out["status"] == "rejected"
    assert "safe" in out["reason"] or "no answer" in out["reason"]


def test_heal_yes_cannot_bypass_policy(tmp_path: Path):
    db = tmp_path / "approvals.sqlite"
    reset_healing_approvals()
    prose = create("heal", "note", detail="proposed css=#purchase", path=db)
    weaken = create("heal", "assert", detail=_detail(_BAD, "auth_problem"), path=db)
    infra = create(
        "heal", "infra", detail=_detail(_GOOD, "infrastructure"), path=db,
    )
    auth = create("heal", "auth", detail=_detail(_GOOD, "auth_problem"), path=db)
    assert decide_approval(prose["id"], "yes", path=db)["status"] == "rejected"
    assert decide_approval(weaken["id"], "yes", path=db)["status"] == "rejected"
    assert decide_approval(infra["id"], "yes", path=db)["status"] == "rejected"
    accepted = decide_approval(auth["id"], "yes", path=db)
    reset_healing_approvals()
    assert accepted["status"] == "accepted"
    assert accepted["reason"] == "a person accepted it"


def test_an_accepted_heal_writes_the_script_once(tmp_path: Path):
    db = tmp_path / "approvals.sqlite"
    run = tmp_path / "run"
    script = run / "generated_tests" / "test_x.py"
    script.parent.mkdir(parents=True)
    script.write_text(_OLD, encoding="utf-8")
    reset_healing_approvals()
    detail = json.dumps({
        "old_code": _OLD, "new_code": _GOOD, "failure_class": "auth_problem",
        "run_dir": str(run), "file": "test_x.py",
    })
    row = create("heal", "locator", detail=detail, path=db)
    accepted = decide_approval(row["id"], "yes", path=db)
    assert accepted["status"] == "accepted"
    assert accepted["heal_applied"] is True
    assert script.read_text(encoding="utf-8") == _GOOD
    again = create("heal", "locator again", detail=detail, path=db)
    reused = decide_approval(again["id"], "yes", path=db)
    assert reused["status"] == "rejected"
    assert "already used" in reused["reason"]
    weaken = json.dumps({
        "old_code": _GOOD, "new_code": _BAD, "failure_class": "auth_problem",
        "run_dir": str(run), "file": "test_x.py",
    })
    script.write_text(_GOOD, encoding="utf-8")
    blocked = create("heal", "weaken", detail=weaken, path=db)
    assert decide_approval(blocked["id"], "yes", path=db)["status"] == "rejected"
    assert script.read_text(encoding="utf-8") == _GOOD
    escaped = json.dumps({
        "old_code": _OLD, "new_code": _GOOD, "failure_class": "locator",
        "run_dir": str(run), "file": "../outside.py",
    })
    outside = tmp_path / "outside.py"
    outside.write_text(_OLD, encoding="utf-8")
    escape = create("heal", "escape", detail=escaped, path=db)
    refused = decide_approval(escape["id"], "yes", path=db)
    assert refused["status"] == "rejected"
    assert outside.read_text(encoding="utf-8") == _OLD


def test_unknown_kind_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        create("ordinary", "x", path=tmp_path / "a.sqlite")


def test_an_old_approval_db_gains_a_tenant_column(tmp_path: Path):
    import sqlite3

    db = tmp_path / "old.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE approvals (id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, "
            "detail TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, answer TEXT NOT NULL DEFAULT '', "
            "reason TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, decided_at REAL)"
        )
    row = create("sensitive", "keep", path=db)
    assert row["tenant_id"] == ""
    assert list_approvals(path=db, tenant_id="")[0]["id"] == row["id"]
    assert list_approvals(path=db, tenant_id="t1") == []


def test_an_approval_stays_in_its_tenant_and_cannot_rewrite_another_test(monkeypatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    import backend.approvals as approvals
    import backend.tenancy_store as tenancy
    from backend import server

    db = tmp_path / "approvals.sqlite"
    runs = tmp_path / "runs"
    script = runs / "run-b" / "generated_tests" / "test_x.py"
    script.parent.mkdir(parents=True)
    script.write_text(_OLD, encoding="utf-8")
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(approvals, "DEFAULT_DB", db)
    monkeypatch.setattr(tenancy, "DEFAULT_DB", tmp_path / "tenancy.sqlite")
    tenancy.upsert_tenant("t1", "One")
    tenancy.upsert_tenant("t2", "Two")
    tenancy.upsert_principal("view-1", "t1", "v@ex.test", "viewer")
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin")
    tenancy.upsert_principal("admin-2", "t2", "b@ex.test", "admin")
    tenancy.index_run("run-b", "t2", source="https://b.test", verdict="Ready")
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    header = {"X-Agentic-QA": "1"}
    made = client.post(
        "/api/approvals", headers={**header, "Authorization": "Bearer admin-1"},
        json={"kind": "sensitive", "subject": "delete the account"},
    )
    assert made.status_code == 200
    approval_id = made.json()["id"]
    hidden = client.get("/api/approvals", headers={"Authorization": "Bearer admin-2"})
    assert hidden.status_code == 200 and hidden.json()["approvals"] == []
    assert client.get("/api/approvals", headers={"Authorization": "Bearer view-1"}).status_code == 403
    other = client.post(
        f"/api/approvals/{approval_id}/decide",
        headers={**header, "Authorization": "Bearer admin-2"}, json={"answer": "yes"},
    )
    assert other.status_code == 403
    assert list_approvals(path=db)[0]["status"] == "pending"
    owner = client.post(
        f"/api/approvals/{approval_id}/decide",
        headers={**header, "Authorization": "Bearer admin-1"}, json={"answer": "yes"},
    )
    assert owner.status_code == 200 and owner.json()["status"] == "accepted"
    detail = json.dumps({
        "old_code": _OLD, "new_code": _GOOD, "failure_class": "auth_problem",
        "run_dir": str(runs / "run-b"), "file": "test_x.py",
    })
    heal = client.post(
        "/api/approvals", headers={**header, "Authorization": "Bearer admin-1"},
        json={"kind": "heal", "subject": "other tenant script", "detail": detail},
    )
    assert heal.status_code == 200
    refused = client.post(
        f"/api/approvals/{heal.json()['id']}/decide",
        headers={**header, "Authorization": "Bearer admin-1"}, json={"answer": "yes"},
    )
    assert refused.status_code == 200
    assert refused.json()["status"] == "rejected"
    assert refused.json()["reason"] == "tenant isolation"
    assert script.read_text(encoding="utf-8") == _OLD


def test_a_heal_can_write_only_inside_that_tenants_run_folder(monkeypatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    import backend.approvals as approvals
    import backend.tenancy_store as tenancy
    from backend import server
    from backend.config import settings
    from backend.healing_policy import reset_healing_approvals

    studio = tmp_path / "studio"
    owned = studio / "run-a" / "generated_tests" / "test_x.py"
    evil = tmp_path / "evil" / "run-a" / "generated_tests" / "test_x.py"
    owned.parent.mkdir(parents=True)
    evil.parent.mkdir(parents=True)
    owned.write_text(_OLD, encoding="utf-8")
    evil.write_text(_OLD, encoding="utf-8")
    db = tmp_path / "approvals.sqlite"
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(settings, "runs_dir", studio)
    monkeypatch.setattr(approvals, "DEFAULT_DB", db)
    monkeypatch.setattr(tenancy, "DEFAULT_DB", tmp_path / "tenancy.sqlite")
    reset_healing_approvals()
    tenancy.upsert_tenant("t1", "One")
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin")
    tenancy.index_run("run-a", "t1", source="https://a.test", verdict="Ready")
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    header = {"X-Agentic-QA": "1", "Authorization": "Bearer admin-1"}

    def decide(run_dir: Path, subject: str):
        detail = json.dumps({
            "old_code": _OLD, "new_code": _GOOD, "failure_class": "auth_problem",
            "run_dir": str(run_dir), "file": "test_x.py",
        })
        made = client.post(
            "/api/approvals", headers=header,
            json={"kind": "heal", "subject": subject, "detail": detail},
        )
        assert made.status_code == 200
        return client.post(f"/api/approvals/{made.json()['id']}/decide", headers=header, json={"answer": "yes"})

    refused = decide(evil.parent.parent, "outside the studio")
    assert refused.status_code == 200
    assert refused.json()["status"] == "rejected"
    assert refused.json()["reason"] == "tenant isolation"
    assert evil.read_text(encoding="utf-8") == _OLD
    accepted = decide(owned.parent.parent, "inside the studio")
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"
    assert owned.read_text(encoding="utf-8") == _GOOD
    assert evil.read_text(encoding="utf-8") == _OLD


def test_a_heal_does_not_follow_a_symlink_out_of_the_run(tmp_path: Path):
    reset_healing_approvals()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = outside / "test_x.py"
    linked.write_text(_OLD, encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    (run / "generated_tests").symlink_to(outside, target_is_directory=True)
    db = tmp_path / "approvals.sqlite"
    detail = json.dumps({
        "old_code": _OLD, "new_code": _GOOD, "failure_class": "auth_problem",
        "run_dir": str(run), "file": "test_x.py",
    })
    row = create("heal", "linked folder", detail=detail, path=db)
    decided = decide_approval(row["id"], "yes", path=db)
    assert decided["status"] == "rejected"
    assert decided["reason"] == "script path must stay inside the run"
    assert linked.read_text(encoding="utf-8") == _OLD

    real = tmp_path / "real"
    real.mkdir()
    (real / "generated_tests").mkdir()
    stolen = tmp_path / "stolen.py"
    stolen.write_text(_OLD, encoding="utf-8")
    (real / "generated_tests" / "test_x.py").symlink_to(stolen)
    detail = json.dumps({
        "old_code": _OLD, "new_code": _GOOD, "failure_class": "auth_problem",
        "run_dir": str(real), "file": "test_x.py",
    })
    row = create("heal", "linked file", detail=detail, path=db)
    decided = decide_approval(row["id"], "yes", path=db)
    assert decided["status"] == "rejected"
    assert stolen.read_text(encoding="utf-8") == _OLD


def test_a_signed_in_heal_does_not_follow_a_run_folder_symlink(monkeypatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    import backend.approvals as approvals
    import backend.tenancy_store as tenancy
    from backend import server
    from backend.config import settings

    studio = tmp_path / "studio"
    studio.mkdir()
    outside = tmp_path / "outside" / "generated_tests"
    outside.mkdir(parents=True)
    script = outside / "test_x.py"
    script.write_text(_OLD, encoding="utf-8")
    (studio / "run-a").symlink_to(tmp_path / "outside", target_is_directory=True)
    db = tmp_path / "approvals.sqlite"
    monkeypatch.setenv("QPILOT_DASHBOARD_AUTH", "principal")
    monkeypatch.setattr(settings, "runs_dir", studio)
    monkeypatch.setattr(approvals, "DEFAULT_DB", db)
    monkeypatch.setattr(tenancy, "DEFAULT_DB", tmp_path / "tenancy.sqlite")
    reset_healing_approvals()
    tenancy.upsert_tenant("t1", "One")
    tenancy.upsert_principal("admin-1", "t1", "a@ex.test", "admin")
    tenancy.index_run("run-a", "t1", source="https://a.test", verdict="Ready")
    client = TestClient(server.app, base_url="http://127.0.0.1:8000")
    header = {"X-Agentic-QA": "1", "Authorization": "Bearer admin-1"}
    detail = json.dumps({
        "old_code": _OLD, "new_code": _GOOD, "failure_class": "auth_problem",
        "run_dir": str(studio / "run-a"), "file": "test_x.py",
    })
    made = client.post(
        "/api/approvals", headers=header,
        json={"kind": "heal", "subject": "linked run", "detail": detail},
    )
    assert made.status_code == 200
    decided = client.post(
        f"/api/approvals/{made.json()['id']}/decide", headers=header, json={"answer": "yes"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "rejected"
    assert decided.json()["reason"] == "tenant isolation"
    assert script.read_text(encoding="utf-8") == _OLD
