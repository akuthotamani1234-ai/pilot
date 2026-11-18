"""Gate B: durable supervisor evidence is recorded for crawled URLs."""
from backend.swarm_evidence import record_swarm


def test_record_swarm_plans_and_drains(tmp_path):
    out = record_swarm(
        tmp_path,
        ["https://shop.example/", "https://shop.example/p/1", "https://shop.example/checkout"],
        run_id="run-swarm",
        worker_count=2,
    )
    assert out["ran"] is True
    assert out["gate_b_complete"] is False
    assert out["processed"] >= 1
    assert (tmp_path / "swarm_evidence.json").is_file()
    assert (tmp_path / "swarm_queue.sqlite").is_file()
    # checkout must not be scheduled as a worker URL
    assert all("/checkout" not in (t.get("url") or "") for t in out["tasks"] if t.get("role") == "worker")
