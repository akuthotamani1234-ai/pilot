"""Gate B: durable supervisor evidence is recorded for crawled URLs."""
from backend.swarm_evidence import mirror_listing, record_swarm
from backend.swarm_protocol import tasks_for_listing


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


def test_listing_dual_write_and_drain(tmp_path):
    listing = tasks_for_listing(
        "https://shop.example/catalog",
        ["https://shop.example/p/1", "https://shop.example/p/2"],
        [("https://shop.example/p/3", "sampled_out")],
        2,
    )
    mirrored = mirror_listing(tmp_path, listing, run_id="run-list")
    assert mirrored["mirrored"] >= 1
    assert (tmp_path / "swarm_listing_mirror.json").is_file()
    out = record_swarm(
        tmp_path,
        ["https://shop.example/"],
        run_id="run-list",
        listing_tasks=listing,
    )
    assert out["ran"] is True
    assert out["listing_mirrored"] >= 1
    assert out["gate_b_complete"] is False
    roles = {t.get("role") for t in out["tasks"]}
    assert "coverage" in roles
    assert "oracle" in roles


def test_plan_includes_specialists():
    from backend.swarm_supervisor import plan_run
    planned = plan_run("run-x", ["https://shop.example/", "https://shop.example/p/1"], worker_count=2)
    roles = {t["role"] for t in planned}
    assert "coverage" in roles
    assert "oracle" in roles
