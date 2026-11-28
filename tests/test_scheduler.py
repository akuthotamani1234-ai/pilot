"""Phase 8: large executions in batches - a prerequisite chain never cut, high priority first, one batch at a time
through the existing engine, results collected per batch, a Studio restart leaves it resumable from the first batch not
done, cancel stops the rest, AI cost summed over the batches."""
import json

import pytest

from backend.atlassian import bridge, scheduler
from tests.test_requirements_execution import _accept, api as requirements_fixture  # noqa: F401


def c(cid, priority="medium"):
    return {"id": cid, "priority": priority}


def test_batches_keep_chains_together_put_high_priority_first_and_respect_the_size():
    cases = [c("A"), c("B"), c("C", "high"), c("D"), c("E"), c("F", "low")]
    chains = {"B": ["A"], "E": ["D", "A"]}  # (A -> B, A -> D -> E: one chain of four)
    batches = scheduler.split(cases, chains, size=2)
    assert batches[0] == ["C"]  # (high priority first)
    chain = next(b for b in batches if "A" in b)
    assert set(chain) == {"A", "B", "D", "E"} and chain.index("A") < chain.index("E")  # (never cut, prereqs first)
    assert batches[-1] == ["F"]  # (low priority last)
    assert sum(len(b) for b in batches) == 6


def test_cost_is_summed_over_the_batch_runs(tmp_path):
    for n, (calls, usd) in enumerate([(3, 0.01), (5, 0.02)]):
        d = tmp_path / f"r{n}"
        d.mkdir()
        (d / "cost.json").write_text(json.dumps({"calls": calls, "tokens_in": 100, "tokens_out": 10, "cost_usd": usd}))
    assert scheduler.cost_of([tmp_path / "r0", tmp_path / "r1", tmp_path / "missing"]) == {
        "calls": 8, "tokens_in": 200, "tokens_out": 20, "cost_usd": 0.03}


@pytest.fixture
def batched(requirements_fixture, monkeypatch):  # noqa: F811
    api = requirements_fixture
    from backend import requirements_api as rapi
    monkeypatch.setattr(scheduler, "BATCH_SIZE", 1)
    _accept(api, 2)
    api.client.post("/api/requirements/items/jira-main/QPL-2/test-cases", headers=api.H)
    launched = []

    def fake_launch(req, caller):  # (each batch = one run of the engine; finished by the test below)
        job = 700 + len(launched)
        run = api.tmp / f"run{job}"
        run.mkdir()
        launched.append((job, [t["tc"] for t in req.requirement_tests]))
        api.server.jobs[job] = {"id": job, "status": "running", "run": ""}
        return {"id": job}
    monkeypatch.setattr(api.server, "_launch_run", fake_launch)
    monkeypatch.setattr(rapi, "_watch", lambda *a, **k: None)  # (the test settles explicitly)
    body = {"strategy": "requirements", "scope": {"test_case_ids": ["TC-QPL-2-1", "TC-QPL-2-2"]},
            "target": {"url": "https://shop.example/", "authorized": True, "test_username": "u",
                       "test_password": "p"}}
    r = api.client.post("/api/requirements/executions", headers=api.H, json=body)
    assert r.status_code == 200, r.text
    return api, launched, r.json()["execution"]["id"]


def _finish(api, job, cases):
    d = api.tmp / f"run{job}"
    (d / "test_cases.json").write_text(json.dumps([{"requirement_test": c, "execution_status": "Passed"}
                                                   for c in cases]))
    monkey = api.server._plain_run_dir
    api.server.jobs[job].update(status="done", run=f"run{job}")
    return d, monkey


def test_a_large_execution_runs_batch_after_batch_and_ends_with_every_outcome(batched, monkeypatch):
    api, launched, ex_id = batched
    assert len(launched) == 1 and len(launched[0][1]) == 1  # (only the first batch started)
    monkeypatch.setattr(api.server, "_plain_run_dir", lambda run: api.tmp / run)
    _finish(api, launched[0][0], launched[0][1])
    e = api.client.get(f"/api/requirements/executions/{ex_id}", headers=api.H).json()
    assert len(launched) == 2 and e["execution"]["status"] == "running"  # (batch 2 started)
    assert [b["status"] for b in e["execution"]["batches"]] == ["done", "running"]
    assert len(e["results"]) == 1  # (batch 1's result is already there)
    _finish(api, launched[1][0], launched[1][1])
    e = api.client.get(f"/api/requirements/executions/{ex_id}", headers=api.H).json()
    assert e["execution"]["status"] == "finished" and e["execution"]["tally"]["passed"] == 2
    assert {r["test_case_id"] for r in e["results"]} == {"TC-QPL-2-1", "TC-QPL-2-2"}


def test_a_restart_leaves_it_resumable_from_the_first_batch_not_done(batched, monkeypatch):
    from backend import requirements_api as rapi
    api, launched, ex_id = batched
    api.server.jobs.pop(launched[0][0])  # (the Studio restarted: the running batch's job is gone)
    rapi._PENDING.pop(ex_id, None)
    e = api.client.get(f"/api/requirements/executions/{ex_id}", headers=api.H).json()["execution"]
    assert e["status"] == "interrupted" and e["batches"][0]["status"] == "interrupted"
    assert e["outcome"] == "interrupted" and "resume" in e["outcome_text"]
    r = api.client.post(f"/api/requirements/executions/{ex_id}/resume", headers=api.H, json={"test_password": "p"})
    assert r.status_code == 200, r.text
    assert r.json()["batch"] == 1 and launched[-1][1] == launched[0][1]  # (the same batch again)
    again = api.client.post(f"/api/requirements/executions/{ex_id}/resume", headers=api.H, json={})
    assert again.status_code == 409


def test_cancel_stops_the_remaining_batches(batched, monkeypatch):
    api, launched, ex_id = batched
    monkeypatch.setattr(api.server, "_plain_run_dir", lambda run: api.tmp / run)
    _finish(api, launched[0][0], launched[0][1])
    api.server.jobs[launched[0][0]]["status"] = "stopped"
    e = api.client.get(f"/api/requirements/executions/{ex_id}", headers=api.H).json()["execution"]
    assert e["status"] == "cancelled" and e["batches"][1]["status"] == "cancelled" and len(launched) == 1
    rows = api.client.get(f"/api/requirements/executions/{ex_id}", headers=api.H).json()["results"]
    assert sorted(r["status"] for r in rows) == ["Cancelled", "Passed"]


def test_provider_block_pauses_other_batches_and_resumes_at_the_checkpoint(batched, monkeypatch):
    api, launched, ex_id = batched
    monkeypatch.setattr(api.server, "_plain_run_dir", lambda run: api.tmp / run)
    first, ids = launched[0]
    (api.tmp / f"run{first}" / "summary.json").write_text(json.dumps({
        "incomplete": True, "stop_kind": "ai_unavailable", "incomplete_reason": "Provider rate-limited (HTTP 429)",
    }))
    api.server.jobs[first].update(status="failed", run=f"run{first}")
    path = f"/api/requirements/executions/{ex_id}"
    payload = api.client.get(path, headers=api.H).json()
    assert [b["status"] for b in payload["execution"]["batches"]] == ["interrupted", "queued"]
    assert payload["results"][0]["blocked_by_provider"]
    assert len(launched) == 1
    assert api.client.post(f"{path}/resume", headers=api.H, json={"test_password": "p"}).status_code == 200
    assert launched[-1][1] == ids
    _finish(api, *launched[-1])
    api.client.get(path, headers=api.H)
    _finish(api, *launched[-1])
    recovered = api.client.get(path, headers=api.H).json()["execution"]
    assert recovered["tally"]["passed"] == 2 and recovered["tally"]["blocked"] == 0
    assert "provider_failure" not in recovered


def test_stale_poll_cannot_collect_the_next_batch_with_the_previous_job(batched, monkeypatch):
    from backend import requirements_api
    api, launched, ex_id = batched
    monkeypatch.setattr(api.server, "_plain_run_dir", lambda run: api.tmp / run)
    db = bridge.connect()
    try:
        tenant = db.execute("SELECT tenant_id FROM req_executions WHERE id=?", (ex_id,)).fetchone()[0]
        stale = bridge.get_execution(db, tenant, ex_id)
        _finish(api, *launched[0])
        requirements_api._settle_execution(db, tenant, stale)
        assert len(launched) == 2
        still_active = requirements_api._settle_execution(db, tenant, stale)
        assert still_active["status"] == "running"
        assert len(bridge.results(db, tenant, ex_id)) == 1
    finally:
        db.close()


def test_validated_independent_cases_run_before_cases_waiting_for_design():
    cases = [{"id": f"TC-X-{i}", "priority": "high"} for i in range(1, 5)]
    assert scheduler.split(cases, {}, size=2, validated={"TC-X-3", "TC-X-4"}) == [
        ["TC-X-3", "TC-X-4"], ["TC-X-1", "TC-X-2"]]
