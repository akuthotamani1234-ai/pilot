"""Phase 3: durable supervisor plans, enqueues, drains, and recovers."""
from backend.swarm_queue import DurableQueue
from backend.swarm_supervisor import drain, enqueue_plan, plan_run


def test_supervisor_drains_safe_pages_and_skips_checkout(tmp_path):
    urls = [
        "https://shop.example/",
        "https://shop.example/product/1",
        "https://shop.example/checkout",
        "https://shop.example/account",
    ]
    q = DurableQueue(tmp_path / "q.sqlite")
    planned = plan_run("run-a", urls, worker_count=2)
    assert all("/checkout" not in (t.get("url") or "") for t in planned if t["role"] == "worker")
    enqueue_plan(q, "run-a", planned)

    seen = []

    def work(task):
        url = task["payload"]["url"]
        seen.append(url)
        return {"evidence": [f"opened {url}"]}

    summary = drain(q, run_id="run-a", worker_id="w1", work=work)
    assert summary["processed"] >= 1
    statuses = {t["task_id"]: t["status"] for t in summary["tasks"]}
    assert "failed" not in statuses.values()
    assert all(s in ("succeeded", "blocked") for s in statuses.values())
    assert "https://shop.example/checkout" not in seen
    q.close()


def test_supervisor_records_worker_crash_as_retry_then_success(tmp_path):
    q = DurableQueue(tmp_path / "q.sqlite", max_attempts=3)
    planned = plan_run("run-b", ["https://shop.example/p/1"], worker_count=1)
    enqueue_plan(q, "run-b", planned)
    attempts = {"n": 0}

    def work(task):
        if task["role"] == "leader":
            return {"evidence": ["planned"]}
        attempts["n"] += 1
        if attempts["n"] == 1:
            err = RuntimeError("browser died")
            err.error_class = "worker_crash"
            raise err
        return {"evidence": ["recovered"]}

    drain(q, run_id="run-b", worker_id="w1", work=work)
    # First drain left worker in retry_wait; claim again.
    drain(q, run_id="run-b", worker_id="w1", work=work)
    rows = q.list_run("run-b")
    worker = next(r for r in rows if r["role"] == "worker")
    assert worker["status"] == "succeeded"
    assert worker["attempt"] >= 2
    q.close()
