"""A Redis queue drill stays in this install. A link does not open the queue."""
from backend.blueprint_progress import progress
from backend.redis_queue_drill import durable_queue_drill


def test_a_redis_queue_drill_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.queue_backend as queues
    import backend.swarm_supervisor as swarm

    calls = {"n": 0}

    class _Queue:
        def close(self):
            return None

    def _open(*_args, **_kwargs):
        calls["n"] += 1
        return {"ready": True, "backend": "redis", "queue": _Queue(), "reason": ""}

    def _plan(*_args, **_kwargs):
        calls["n"] += 1
        return []

    def _enqueue(*_args, **_kwargs):
        calls["n"] += 1
        return []

    def _drain(*_args, **_kwargs):
        calls["n"] += 1
        return {
            "processed": 1,
            "tasks": [
                {"status": "done", "role": "coverage"},
                {"status": "done", "role": "oracle"},
            ],
        }

    monkeypatch.setattr(queues, "open_durable_queue", _open)
    monkeypatch.setattr(swarm, "plan_run", _plan)
    monkeypatch.setattr(swarm, "enqueue_plan", _enqueue)
    monkeypatch.setattr(swarm, "drain", _drain)

    secret = "tenant-b-redis-queue"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "redis_durable_queue_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = durable_queue_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_b_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = durable_queue_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    planted.unlink()

    saved = durable_queue_drill(ops_dir=real, url="redis://127.0.0.1:6379/0")
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_b_complete"] is False
    assert saved["gate_g_complete"] is False
    assert saved["ok"] is True
    assert "coverage" in saved["roles"]
    assert calls["n"] == 5
    assert "DurableQueue" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_redis_queue_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-redis-queue-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-redis-queue-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "B")["status"] != "done"
    assert snap["complete"] is False
