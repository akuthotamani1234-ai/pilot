"""A cutover rehearsal stays in this install. A link does not start the bundled checks."""
from backend.blueprint_progress import progress
from backend.multi_region_cutover_rehearsal_drill import (
    run_multi_region_cutover_rehearsal_drill,
)


def test_a_cutover_rehearsal_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.failover_rto_drill as failover
    import backend.minio_multi_region_drill as minio
    import backend.multi_region_dr_drill as region
    import backend.multi_store_dr_drill as store
    import backend.redis_multi_region_drill as redis

    calls = {"n": 0}

    def _pass(**_kwargs):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(region, "run_multi_region_dr_drill", _pass)
    monkeypatch.setattr(minio, "run_minio_multi_region_drill", _pass)
    monkeypatch.setattr(redis, "run_redis_multi_region_drill", _pass)
    monkeypatch.setattr(store, "run_multi_store_dr_drill", _pass)
    monkeypatch.setattr(failover, "run_failover_rto_drill", _pass)

    secret = "tenant-b-rehearsal"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "multi_region_cutover_rehearsal_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_multi_region_cutover_rehearsal_drill(ops_dir=linked)
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
    skipped = run_multi_region_cutover_rehearsal_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_multi_region_cutover_rehearsal_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["ok"] is True
    assert saved["steps_passed"] == 5
    assert calls["n"] == 5
    assert "cutover rehearsal" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_cutover_rehearsal_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-cutover-rehearsal-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-cutover-rehearsal-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
