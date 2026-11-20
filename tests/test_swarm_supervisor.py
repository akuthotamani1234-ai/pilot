"""Phase 3: durable supervisor plans, enqueues, drains, and recovers."""
import time

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


def test_drain_never_opens_a_payment_url(tmp_path):
    q = DurableQueue(tmp_path / "q.sqlite", lease_seconds=30)
    q.enqueue(
        run_id="run-pay", role="worker",
        payload={"url": "https://shop.example/checkout"},
        idempotency_key="pay",
    )
    seen = []

    def work(task):
        seen.append(task["payload"]["url"])
        return {"ok": True}

    summary = drain(q, run_id="run-pay", worker_id="w1", work=work)
    assert seen == []
    assert summary["processed"] == 1
    assert summary["gate_b_complete"] is False
    row = summary["tasks"][0]
    assert row["status"] == "failed"
    assert row["error_class"] == "rule_violation"
    q.close()


def test_a_retried_task_resumes_from_the_checkpoint(tmp_path):
    q = DurableQueue(tmp_path / "q.sqlite", lease_seconds=30, max_attempts=3)
    q.enqueue(
        run_id="run-r", role="worker",
        payload={"url": "https://shop.example/product/1"},
        idempotency_key="product",
    )
    seen = []

    def work(task):
        seen.append(task.get("checkpoint"))
        if not task.get("checkpoint"):
            return {
                "error_class": "worker_crash",
                "detail": "browser closed",
                "checkpoint": {"step": 2, "url": "https://shop.example/product/1"},
            }
        return {"ok": True, "resumed": task["checkpoint"]["step"]}

    summary = drain(q, run_id="run-r", worker_id="w1", work=work)
    row = summary["tasks"][0]
    assert seen == [None, {"step": 2, "url": "https://shop.example/product/1"}]
    assert row["status"] == "succeeded"
    assert row["attempt"] == 2
    assert row["checkpoint"] == {"step": 2, "url": "https://shop.example/product/1"}
    assert row["result"]["resumed"] == 2
    q.close()


def test_a_retry_does_not_resume_on_checkout(tmp_path):
    q = DurableQueue(tmp_path / "q.sqlite", lease_seconds=30, max_attempts=3)
    q.enqueue(
        run_id="run-pay", role="worker",
        payload={"url": "https://shop.example/product/1"},
        idempotency_key="product",
    )
    seen = []

    def work(task):
        seen.append(task.get("checkpoint"))
        if len(seen) == 1:
            return {
                "error_class": "worker_crash",
                "detail": "landed on checkout",
                "checkpoint": {"step": 1, "url": "https://shop.example/checkout"},
            }
        return {"ok": True}

    summary = drain(q, run_id="run-pay", worker_id="w1", work=work)
    assert seen == [None, None]
    row = summary["tasks"][0]
    assert row["status"] == "succeeded"
    assert row["checkpoint"] is None
    q.close()


def test_a_retry_does_not_keep_a_checkout_landing(tmp_path):
    q = DurableQueue(tmp_path / "q.sqlite", lease_seconds=30, max_attempts=3)
    q.enqueue(
        run_id="run-land", role="worker",
        payload={"url": "https://shop.example/cart"},
        idempotency_key="cart",
    )
    seen = []

    def work(task):
        seen.append(task.get("checkpoint"))
        if len(seen) == 1:
            return {
                "error_class": "worker_crash",
                "detail": "cart redirected",
                "checkpoint": {
                    "step": 1,
                    "url": "https://shop.example/cart",
                    "final_url": "https://shop.example/index.php?rt=checkout/confirm",
                },
            }
        return {"ok": True}

    summary = drain(q, run_id="run-land", worker_id="w1", work=work)
    assert seen == [None, None]
    row = summary["tasks"][0]
    assert row["status"] == "succeeded"
    assert row["checkpoint"] is None
    assert summary["gate_b_complete"] is False
    q.close()


def test_drain_stops_when_the_lease_expires_during_work(tmp_path):
    q = DurableQueue(tmp_path / "q.sqlite", lease_seconds=30)
    q.enqueue(run_id="run-c", role="worker", payload={"url": "/slow"}, idempotency_key="slow")

    def work(task):
        q._db.execute(
            "UPDATE tasks SET lease_until=? WHERE task_id=?",
            (time.time() - 1, task["task_id"]),
        )
        q._db.commit()
        return {"evidence": ["too late"]}

    summary = drain(q, run_id="run-c", worker_id="w1", work=work)
    assert summary["processed"] == 0
    assert summary["gate_b_complete"] is False
    assert summary["lease_lost"]
    row = q.get(summary["lease_lost"][0])
    assert row["status"] == "leased"
    assert row["result"] is None
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
