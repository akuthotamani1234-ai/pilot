"""A swarm contention drill stays in this install. A link does not open the queue."""
from backend.blueprint_progress import progress
from backend.redis_swarm_contention_drill import run_redis_swarm_contention_drill


def test_a_swarm_contention_drill_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.redis_swarm_contention_drill as mod

    calls = {"n": 0}

    class _Queue:
        def __init__(self):
            self.items = []
            self.claimed = set()

        def enqueue(self, **kwargs):
            self.items.append(kwargs["payload"]["task_id"])

        def claim(self, worker_id, run_id):
            for task_id in self.items:
                if task_id not in self.claimed:
                    self.claimed.add(task_id)
                    return {"task_id": task_id}
            return None

    def _open(*_args, **_kwargs):
        calls["n"] += 1
        return {"ready": True, "backend": "redis", "queue": _Queue()}

    monkeypatch.setattr(mod, "open_durable_queue", _open)
    root = tmp_path / "root"
    monkeypatch.setattr(mod, "ROOT", root)

    secret = "tenant-b-swarm-queue"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "redis_swarm_contention_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_redis_swarm_contention_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_b_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_redis_swarm_contention_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    (root / "artifacts").mkdir(parents=True)
    queue_link = root / "artifacts" / "ops"
    queue_link.symlink_to(other, target_is_directory=True)
    unread = run_redis_swarm_contention_drill(ops_dir=real)
    assert unread["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(unread)
    assert [path.name for path in other.iterdir()] == [kept.name]
    queue_link.unlink()

    saved = run_redis_swarm_contention_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_b_complete"] is False
    assert saved["ok"] is True
    assert saved["total_claimed"] == 4
    assert calls["n"] == 1
    assert "distinct tasks" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_swarm_contention_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-swarm-contention-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-swarm-contention-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "B")["status"] != "done"
    assert snap["complete"] is False
