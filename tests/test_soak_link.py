"""A controlled soak stays in this install. A link does not start the portal."""
from backend.blueprint_progress import progress
from backend.ops_soak_drill import run_controlled_soak


def test_a_controlled_soak_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.ops_soak_drill as mod
    import tests.admin_portal as portal_mod

    calls = {"portal": 0, "http": 0}
    clock = {"n": 1000.0}

    def _now():
        clock["n"] += 0.2
        return clock["n"]

    class _Portal:
        def __init__(self, _port, bugs=False):
            self.url = "http://127.0.0.1:9"

        def start(self):
            calls["portal"] += 1
            return self

        def stop(self):
            return None

    def _get(_url):
        calls["http"] += 1
        return 200

    monkeypatch.setattr(mod.time, "perf_counter", _now)
    monkeypatch.setattr(portal_mod, "AdminPortal", _Portal)
    monkeypatch.setattr(mod, "_http_get", _get)

    secret = "tenant-b-soak"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "controlled_soak_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_controlled_soak(ops_dir=linked, duration_s=5)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert calls["portal"] == 0
    assert calls["http"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_controlled_soak(ops_dir=real, duration_s=5)
    assert skipped["ok"] is False
    assert calls["portal"] == 0
    assert calls["http"] == 0
    planted.unlink()

    saved = run_controlled_soak(ops_dir=real, duration_s=5)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["ok"] >= 6
    assert saved["fail"] == 0
    assert calls["portal"] == 1
    assert calls["http"] >= 6
    assert "AdminPortal soak" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_soak_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-soak-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-soak-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
