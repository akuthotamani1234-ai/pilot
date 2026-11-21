"""Explorer browsers share one durable queue: concurrent claims must not kill a worker, and a worker error is
reported and its task released instead of being lost (OrangeHRM runs lost one explorer to sqlite3.InterfaceError)."""
import threading

from backend.swarm import SiteSwarm
from backend.swarm_queue import DurableQueue


def test_many_threads_claim_from_one_queue_without_errors(tmp_path):
    queue = DurableQueue(tmp_path / "queue.sqlite")
    tasks = [queue.enqueue(run_id="r", role="browser", payload={"url": f"https://a.test/{i}"}) for i in range(80)]
    errors, claimed = [], []

    def worker(n):
        try:
            for task in tasks[n::8]:
                got = queue.claim_task(task["task_id"], worker_id=f"w{n}")
                if got:
                    claimed.append(got["task_id"])
                    queue.complete(got["task_id"], f"w{n}", {"ok": True, "evidence": [{"kind": "test", "artifact": "fixture.json"}]})
        except Exception as exc:
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(set(claimed)) == 80
    assert {row["status"] for row in queue.list_run("r")} == {"succeeded"}
    queue.close()


def test_a_worker_error_is_reported_and_the_worker_keeps_going(tmp_path):
    queue = DurableQueue(tmp_path / "queue.sqlite")
    notes = []

    def session():
        def open_page(url):
            if url.endswith("/boom"):
                raise RuntimeError("browser crashed")
            return {"url": url, "status": 200, "final_url": url, "summary": "ok"}
        return open_page, lambda: None

    swarm = SiteSwarm(1, 3, session, on_status=lambda w, s, u: notes.append((s, u)), durable_queue=queue,
                      run_id="r", evidence_dir=tmp_path)
    swarm.submit(["https://a.test/one", "https://a.test/boom", "https://a.test/two"])
    rows = swarm.finish()
    by_url = {r["url"]: r for r in rows}
    assert by_url["https://a.test/one"]["durable_status"] == "succeeded"
    assert by_url["https://a.test/two"]["durable_status"] == "succeeded"  # the worker went on after the error
    assert by_url["https://a.test/boom"]["durable_status"] == "failed"
    assert queue.get(by_url["https://a.test/boom"]["task_id"])["status"] in ("failed", "retry_wait")
    queue.close()


def test_an_unexpected_worker_error_is_recorded_not_lost(tmp_path):
    queue = DurableQueue(tmp_path / "queue.sqlite")
    notes = []

    def session():
        return (lambda url: {"url": url, "status": 200, "final_url": url}), (lambda: None)

    swarm = SiteSwarm(1, 2, session, on_status=lambda w, s, u: notes.append((s, u)), durable_queue=queue,
                      run_id="r", evidence_dir=tmp_path)
    real_claim = queue.claim_task
    calls = {"n": 0}

    def flaky_claim(task_id, *, worker_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database misuse")
        return real_claim(task_id, worker_id=worker_id)

    queue.claim_task = flaky_claim
    swarm.submit(["https://a.test/x", "https://a.test/y"])
    rows = swarm.finish()
    assert len(swarm.errors) == 1 and "database misuse" in swarm.errors[0]["error"]
    assert any(s == "stopped" and "worker error" in u for s, u in notes)
    assert {r["url"]: r["durable_status"] for r in rows}["https://a.test/y"] == "succeeded"
    queue.close()
