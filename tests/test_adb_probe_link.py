"""An ADB probe stays in this install. A link does not start adb."""
from backend.android_adb_probe import run_adb_probe
from backend.blueprint_progress import progress


def test_an_adb_probe_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.android_adb_probe as mod

    calls = {"n": 0}

    def _env():
        calls["n"] += 1
        return {"adb": "/usr/bin/adb", "devices": [], "errors": []}

    def _enrich(adb, devices):
        calls["n"] += 1
        assert adb == "/usr/bin/adb"
        return list(devices)

    monkeypatch.setattr("backend.android.android_environment", _env)
    monkeypatch.setattr(mod, "_enrich_api_levels", _enrich)

    secret = "tenant-b-adb"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "android_adb_probe.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_adb_probe(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_adb_probe(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_adb_probe(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["ok"] is True
    assert saved["devices_online"] == 0
    assert calls["n"] == 2
    assert "ADB present" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_adb_probe_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-adb-probe-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-adb-probe-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert snap["complete"] is False
