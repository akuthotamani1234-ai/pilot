"""A Redis lease stays in this install. A link does not start redis-cli."""
from subprocess import CompletedProcess

from backend.blueprint_progress import progress
from backend.redis_drill import lease_drill


def test_a_redis_lease_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.redis_drill as mod

    calls = {"n": 0}

    def _cli(_url, *cmd):
        calls["n"] += 1
        name = cmd[0]
        stdout = ""
        if name == "PING":
            stdout = "PONG\n"
        elif name == "SET" and "worker-a" in cmd:
            stdout = "OK\n"
        elif name == "SET":
            stdout = "(nil)\n"
        elif name == "GET":
            stdout = "worker-a\n"
        return CompletedProcess(args=list(cmd), returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(mod, "_cli", _cli)

    secret = "tenant-b-redis-lease"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "redis_lease_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = lease_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_g_complete"] is False
    assert refused["gate_b_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = lease_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    planted.unlink()

    saved = lease_drill(ops_dir=real, url="redis://127.0.0.1:6379/0")
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_g_complete"] is False
    assert saved["gate_b_complete"] is False
    assert saved["ok"] is True
    assert saved["owner"] == "worker-a"
    assert calls["n"] == 5
    assert "SETNX" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_redis_lease_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-redis-lease-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-redis-lease-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "B")["status"] != "done"
    assert snap["complete"] is False
