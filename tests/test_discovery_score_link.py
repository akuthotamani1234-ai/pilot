"""A discovery score stays in this install. A link does not start the inventories."""
from backend.blueprint_progress import progress
from backend.discovery_score_drill import run_discovery_score_drill


def test_a_discovery_score_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.surface_evidence_drill as surfaces

    calls = {"n": 0}

    def _pass(**_kwargs):
        calls["n"] += 1
        return {
            "fixture": "local",
            "pages_walked": ["a", "b", "c"],
            "surfaces": {"frames": [1], "shadow": [1], "dialogs": [1]},
        }

    for name in (
        "run_admin_portal_surface_drill",
        "run_demo_store_surface_drill",
        "run_classic_shop_surface_drill",
        "run_travel_site_surface_drill",
    ):
        monkeypatch.setattr(surfaces, name, _pass)

    secret = "tenant-b-score"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "discovery_score_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_discovery_score_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_a_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_discovery_score_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_discovery_score_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_a_complete"] is False
    assert saved["ok"] is True
    assert saved["passed"] == 4
    assert calls["n"] == 4
    assert "Discovery score" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_discovery_score_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-discovery-score-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-discovery-score-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "A")["status"] != "done"
    assert snap["complete"] is False
