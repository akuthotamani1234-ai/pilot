"""Regression tests for honest swarm worker completion semantics."""
from backend.swarm_queue import DurableQueue
from backend.swarm_supervisor import drain


def test_negative_worker_result_cannot_succeed(tmp_path):
    queue = DurableQueue(tmp_path / "queue.sqlite")
    try:
        task = queue.enqueue(run_id="run1", role="worker", payload={"url": "https://example.test/"})
        result = drain(
            queue, run_id="run1", worker_id="worker-1",
            work=lambda _: {"ok": False, "reason": "no browser evidence"},
        )
        saved = queue.get(task["task_id"])
        assert result["processed"] == 1
        assert saved["status"] == "failed"
        assert saved["error_class"] == "worker_rejected"
    finally:
        queue.close()


def test_positive_worker_result_can_succeed(tmp_path):
    queue = DurableQueue(tmp_path / "queue.sqlite")
    try:
        task = queue.enqueue(run_id="run2", role="worker", payload={"url": "https://example.test/"})
        drain(
            queue, run_id="run2", worker_id="worker-1",
            work=lambda _: {"ok": True, "evidence": [
                {"kind": "browser_observation", "artifact": "fixture-work.json"},
            ]},
        )
        assert queue.get(task["task_id"])["status"] == "succeeded"
    finally:
        queue.close()


def test_unstructured_evidence_cannot_succeed(tmp_path):
    queue = DurableQueue(tmp_path / "queue.sqlite")
    try:
        task = queue.enqueue(run_id="run3", role="worker", payload={"url": "https://example.test/"})
        drain(
            queue, run_id="run3", worker_id="worker-1",
            work=lambda _: {"ok": True, "evidence": ["scheduled but not observed"]},
        )
        saved = queue.get(task["task_id"])
        assert saved["status"] == "failed"
        assert saved["error_class"] == "evidence_missing"
    finally:
        queue.close()
