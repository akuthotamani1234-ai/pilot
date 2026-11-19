"""A swarm control drill stays in this install. A link does not open the queue."""
from backend.blueprint_progress import progress
from backend.swarm_control_drill import run_swarm_control_drill


def test_a_swarm_control_drill_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.swarm_control_drill as mod

    calls = {"n": 0}
    real_open = mod.open_durable_queue

    def _open(*args, **kwargs):
        calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(mod, "open_durable_queue", _open)
    root = tmp_path / "root"
    monkeypatch.setattr(mod, "ROOT", root)

    secret = "tenant-b-swarm-control"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "swarm_control_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_swarm_control_drill(ops_dir=linked, run_id="linked-control")
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
    skipped = run_swarm_control_drill(ops_dir=real, run_id="planted-control")
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    queue_dir = root / "artifacts" / "ops"
    queue_dir.parent.mkdir(parents=True)
    queue_dir.symlink_to(other, target_is_directory=True)
    unread = run_swarm_control_drill(ops_dir=real, run_id="queue-link")
    assert unread["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(unread)
    assert not any(path.suffix == ".sqlite" for path in other.iterdir())
    assert kept.read_bytes() == original
    queue_dir.unlink()
    queue_dir.mkdir()

    saved = run_swarm_control_drill(ops_dir=real, run_id="saved-control")
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_b_complete"] is False
    assert saved["ok"] is True
    assert saved["final_status"] == "cancelled"
    assert calls["n"] == 1
    assert "Swarm control" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_swarm_control_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-swarm-control-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-swarm-control-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "B")["status"] != "done"
    assert snap["complete"] is False
