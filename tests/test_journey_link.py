"""A cross-platform journey stays in this install. A link does not start the shop."""
from backend.blueprint_progress import progress
from backend.cross_platform_journey_drill import run_cross_platform_journey_drill


def test_a_cross_platform_journey_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.cross_platform_journey_drill as mod
    import tests.demo_store as demo

    calls = {"n": 0}

    class _Store:
        url = "http://127.0.0.1:9/"

        def start(self):
            calls["n"] += 1
            return self

        def stop(self):
            return None

    def _web(_engine, _url):
        calls["n"] += 1
        return ["open_home", "open_about"]

    def _android():
        calls["n"] += 1
        return None

    monkeypatch.setattr(demo, "DemoStore", _Store)
    monkeypatch.setattr(mod, "_web_steps", _web)
    monkeypatch.setattr(mod, "_android_steps", _android)

    secret = "tenant-b-journey"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "cross_platform_journey_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_cross_platform_journey_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert refused["gate_f_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_cross_platform_journey_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_cross_platform_journey_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["gate_f_complete"] is False
    assert saved["ok"] is True
    assert calls["n"] == 5
    assert "Cross-platform journey" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_journey_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-journey-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-journey-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "F")["status"] != "done"
    assert snap["complete"] is False
