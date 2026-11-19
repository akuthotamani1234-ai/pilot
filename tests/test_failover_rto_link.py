"""A failover measurement stays in this install. A link does not start the store checks."""
from backend.blueprint_progress import progress
from backend.failover_rto_drill import run_failover_rto_drill


def test_a_failover_measurement_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.minio_multi_region_drill as minio
    import backend.multi_region_dr_drill as region
    import backend.redis_multi_region_drill as redis

    calls = {"n": 0}

    def _pass(**_kwargs):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(region, "run_multi_region_dr_drill", _pass)
    monkeypatch.setattr(minio, "run_minio_multi_region_drill", _pass)
    monkeypatch.setattr(redis, "run_redis_multi_region_drill", _pass)

    secret = "tenant-b-rto"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "failover_rto_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_failover_rto_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_failover_rto_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_failover_rto_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["ok"] is True
    assert saved["passed"] == 3
    assert calls["n"] == 3
    assert "failover RTO" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_failover_rto_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-failover-rto-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-failover-rto-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
