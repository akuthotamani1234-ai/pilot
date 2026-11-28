"""Connection, workflow and execution status come from what really happened (26-28 Nov audit):
- a saved token - or one in .env - is never 'connected'; only Atlassian's answer is; a changed token is unverified;
- Jira and Confluence are independent; a refused token is 'failed', an unreachable site 'unreachable';
- the workflow stages are coloured from their own facts (nothing green because Jira connected);
- an import never starts without a usable connection;
- an execution whose job is gone (Studio restart), or whose job number now belongs to another Studio process, is
  never shown running and never collects another run's results.
Mock Atlassian (tests/atlassian_mock.py) - real HTTP, simulated Jira."""
import pytest

from backend import requirements_api as rapi
from backend.atlassian import bridge
from tests.atlassian_mock import TOKEN
from tests.test_requirements_api import CONN, H, api, mock, wait_job  # noqa: F401

CONF = {"id": "conf-main", "product": "confluence", "site_url": CONN["site_url"], "email": CONN["email"]}


def _status(api, verify=True):  # noqa: F811
    r = api.get(f"/api/requirements/connections/status?verify={'true' if verify else 'false'}", headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _wf(api):  # noqa: F811
    return api.get("/api/requirements/workflow", headers=H).json()["state"]


def test_nothing_is_connected_until_atlassian_answers(api, monkeypatch):  # noqa: F811
    assert _status(api)["jira"]["state"] == "not_connected" and _status(api)["confluence"]["state"] == "not_connected"
    st = _wf(api)
    assert st["stages"]["connect"]["status"] == "pending" and st["stages"]["import"]["status"] == "blocked"
    api.post("/api/requirements/connections", headers=H, json=CONN)
    assert _status(api)["jira"]["state"] == "not_configured"
    monkeypatch.setenv("JIRA_READ_API_TOKEN", "an-old-token-left-in-dotenv")  # (never connected in the Studio)
    assert _status(api, verify=False)["jira"]["state"] == "unverified"  # (saved somewhere is not connected)
    assert not _wf(api)["done"]["connect"]
    assert _status(api)["jira"]["state"] == "failed"  # (asked: Atlassian refuses it)
    assert _wf(api)["stages"]["connect"]["status"] == "failed"
    monkeypatch.delenv("JIRA_READ_API_TOKEN")
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    assert _status(api, verify=False)["jira"]["state"] == "unverified"  # (a new token: not yet asked)
    assert _status(api)["jira"]["state"] == "connected"
    st = _wf(api)
    assert st["done"]["connect"] and st["stages"]["connect"]["status"] == "done"
    assert st["stages"]["import"]["status"] == "pending"  # (connected does not make the next stages green)
    assert [s for s, v in st["stages"].items() if v["status"] == "done"] == ["connect"]
    assert _status(api)["confluence"]["state"] == "not_connected"  # (Confluence is not Jira)


def test_a_wrong_token_is_failed_and_replacing_it_reverifies(api):  # noqa: F811
    api.post("/api/requirements/connections", headers=H, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": "WRONG-TOKEN-123456"})
    r = api.post("/api/requirements/connections/jira-main/test", headers=H)
    assert r.status_code >= 400
    s = _status(api, verify=False)
    assert s["jira"]["state"] == "failed" and s["connections"][0]["checked_at"]
    imp = api.post("/api/requirements/connections/jira-main/imports", headers=H, json={"mode": "items", "keys": "SHOP-1"})
    assert imp.status_code == 424 and "refused" in imp.json()["detail"]["message"]  # (never started)
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    assert api.post("/api/requirements/connections/jira-main/test", headers=H).json()["state"] == "connected"
    assert _status(api, verify=False)["jira"]["state"] == "connected"


def test_an_unreachable_site_is_not_failed_credentials(api, mock):  # noqa: F811
    api.post("/api/requirements/connections", headers=H, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    mock.fail("/rest/api/3/myself", 503, times=10)
    api.post("/api/requirements/connections/jira-main/test", headers=H)
    st = _status(api, verify=False)["jira"]
    assert st["state"] == "unreachable" and _wf(api)["stages"]["connect"]["status"] == "attention"


def test_jira_and_confluence_states_are_independent(api):  # noqa: F811
    api.post("/api/requirements/connections", headers=H, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    api.post("/api/requirements/connections", headers=H, json=CONF)
    s = _status(api)
    assert s["jira"]["state"] == "connected" and s["confluence"]["state"] == "not_configured"


def test_stages_follow_the_real_import_and_never_turn_green_together(api):  # noqa: F811
    api.post("/api/requirements/connections", headers=H, json=CONN)
    api.put("/api/requirements/connections/jira-main/token", headers=H, json={"token": TOKEN})
    _status(api)
    wait_job(api, api.post("/api/requirements/connections/jira-main/imports", headers=H,
                           json={"mode": "items", "keys": "SHOP-1"}).json())
    st = _wf(api)
    assert st["stages"]["import"]["status"] == "done" and st["stages"]["explorer"]["status"] == "pending"
    assert {st["stages"][s]["status"] for s in ("analysis", "reviews", "builder", "execution", "agents",
                                                "reports")} <= {"blocked", "pending"}


def _execution(api, monkeypatch, job_state):  # noqa: F811
    """An execution attached to a Studio job (the engine itself is not run)."""
    from backend import server
    db = bridge.connect()
    try:
        ex = bridge.plan(db, "local", [], "autonomous", {"url": "https://shop.example/"})["execution"]
        server.jobs[7] = {"id": 7, "status": job_state, "run": ""}
        bridge.attach_run(db, "local", ex["id"], "7", boot=server.BOOT_ID)
        return ex["id"]
    finally:
        db.close()


def test_a_running_execution_is_running_only_while_its_job_runs(api, monkeypatch):  # noqa: F811
    from backend import server
    ex_id = _execution(api, monkeypatch, "running")
    api.put("/api/requirements/workflow/draft", headers=H, json={"changes": {"execution_id": ex_id}})
    assert _wf(api)["stages"]["execution"]["status"] == "running"
    server.jobs.pop(7)  # (the Studio restarted: the job is gone)
    e = api.get(f"/api/requirements/executions/{ex_id}", headers=H).json()["execution"]
    assert e["status"] == "interrupted" and e["outcome"] == "interrupted_run"
    assert _wf(api)["stages"]["execution"]["status"] == "attention"


def test_a_job_number_from_another_studio_process_is_never_this_executions_job(api, monkeypatch):  # noqa: F811
    from backend import server
    ex_id = _execution(api, monkeypatch, "running")
    monkeypatch.setattr(server, "BOOT_ID", "a-new-studio-process")  # (restart; job 7 is now someone else's run)
    server.jobs[7] = {"id": 7, "status": "done", "run": "another-run"}
    e = api.get(f"/api/requirements/executions/{ex_id}", headers=H).json()["execution"]
    assert e["status"] == "interrupted" and e.get("counts", {}).get("Passed") is None
