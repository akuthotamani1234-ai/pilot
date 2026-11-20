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
    assert out["backend"] in {"sqlite", "redis"}
    assert (tmp_path / "swarm_evidence.json").is_file()
    if out["backend"] == "sqlite":
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


def test_a_swarm_record_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("QPILOT_REDIS_URL", raising=False)
    secret = b"tenant-b-only-swarm"
    other = tmp_path / "other"
    nested = other / "run"
    nested.mkdir(parents=True)
    (nested / "keep.txt").write_bytes(secret)
    linked = tmp_path / "linked"
    linked.symlink_to(other, target_is_directory=True)
    listing = tasks_for_listing(
        "https://shop.example/catalog",
        ["https://shop.example/p/1"],
        [],
        1,
    )
    mirrored = mirror_listing(linked / "run", listing, run_id="linked")
    recorded = record_swarm(linked / "run", ["https://shop.example/saree"], run_id="linked")
    missing = record_swarm(linked / "fresh", ["https://shop.example/saree"], run_id="fresh")
    assert mirrored["mirrored"] == 0
    assert recorded["ran"] is False and "link" in recorded["reason"]
    assert missing["ran"] is False and "link" in missing["reason"]
    assert not (other / "fresh").exists()
    assert not (nested / "swarm_queue.sqlite").exists()
    assert not (nested / "swarm_evidence.json").exists()
    assert (nested / "keep.txt").read_bytes() == secret

    real = tmp_path / "real"
    saved = record_swarm(real, ["https://shop.example/saree"], run_id="real")
    assert saved["ran"] is True
    evidence = real / "swarm_evidence.json"
    assert evidence.is_file() and not evidence.is_symlink()
    assert secret not in evidence.read_bytes()
    assert (nested / "keep.txt").read_bytes() == secret


def test_plan_includes_specialists():
    from backend.swarm_supervisor import plan_run
    planned = plan_run("run-x", ["https://shop.example/", "https://shop.example/p/1"], worker_count=2)
    roles = {t["role"] for t in planned}
    assert "coverage" in roles
    assert "oracle" in roles
