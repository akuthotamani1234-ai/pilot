"""A cutover lag gate stays in this install. A link is left unread."""
from backend.blueprint_progress import progress
from backend.dual_region_cutover_lag_gate_drill import (
    run_dual_region_cutover_lag_gate_drill,
)


def _stores(**_kwargs):
    return {
        "ok": True,
        "stores": [
            {"store": "postgres", "ok": True, "elapsed_ms": 400},
            {"store": "redis", "ok": True, "elapsed_ms": 120},
            {"store": "minio", "ok": True, "elapsed_ms": 300},
        ],
    }


def test_a_cutover_lag_gate_does_not_follow_a_link(tmp_path, monkeypatch):
    calls = {"n": 0}

    def _counting(**kwargs):
        calls["n"] += 1
        return _stores(**kwargs)

    monkeypatch.setattr(
        "backend.failover_rto_drill.run_failover_rto_drill",
        _counting,
    )
    secret = "tenant-b-lag"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "dual_region_cutover_lag_gate_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_dual_region_cutover_lag_gate_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]
    assert calls["n"] == 0

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_dual_region_cutover_lag_gate_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    assert calls["n"] == 0
    planted.unlink()

    saved = run_dual_region_cutover_lag_gate_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["live_hosted_dr"] is False
    assert saved["ok"] is True
    assert saved["cutover_blocked"] is False
    assert calls["n"] == 1
    assert "Local cutover lag gate evaluated" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_cutover_lag_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-cutover-lag-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-cutover-lag-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
