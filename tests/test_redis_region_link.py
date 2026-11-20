"""A Redis failover stays in this install. A link does not start redis-cli."""
import subprocess

from backend.blueprint_progress import progress
from backend.redis_multi_region_drill import run_redis_multi_region_drill


def test_a_redis_failover_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.redis_multi_region_drill as mod

    calls = {"n": 0}
    store = {"0": None, "1": None}

    def _cli(url, *cmd):
        calls["n"] += 1
        db = "1" if str(url).rstrip("/").endswith("/1") else "0"
        op = cmd[0]
        if op == "PING":
            out = "PONG"
        elif op == "SET":
            store[db] = cmd[2]
            out = "OK"
        elif op == "DEL":
            store[db] = None
            out = "1"
        else:
            out = store[db] or ""
        return subprocess.CompletedProcess(args=["redis-cli"], returncode=0, stdout=out + "\n", stderr="")

    monkeypatch.setattr(mod, "_cli", _cli)

    secret = "tenant-b-redis"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "redis_multi_region_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_redis_multi_region_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert refused["gate_b_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_redis_multi_region_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_redis_multi_region_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["gate_b_complete"] is False
    assert saved["ok"] is True
    assert calls["n"] == 10
    assert "dual-DB" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_redis_region_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-redis-region-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-redis-region-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "B")["status"] != "done"
    assert snap["complete"] is False
