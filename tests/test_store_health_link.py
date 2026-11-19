"""A store health probe stays in this install. A link does not start the probe."""
from backend.blueprint_progress import progress
from backend.dual_region_store_health_probe_drill import (
    run_dual_region_store_health_probe_drill,
)


def test_a_store_health_probe_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.dual_region_store_health_probe_drill as mod

    calls = {"n": 0}

    def _up(host, port, timeout=1.5):
        calls["n"] += 1
        return True

    monkeypatch.setattr(mod, "_tcp_ok", _up)

    secret = "tenant-b-health"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "dual_region_store_health_probe_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_dual_region_store_health_probe_drill(ops_dir=linked)
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
    skipped = run_dual_region_store_health_probe_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_dual_region_store_health_probe_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["live_hosted_dr"] is False
    assert saved["ok"] is True
    assert saved["primary_up"] == 3
    assert calls["n"] == 6
    assert "store health probe" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_store_health_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-store-health-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-store-health-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
