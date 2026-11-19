"""A healing pack stays in this install. A link is left unwritten."""
from backend.blueprint_progress import progress
from backend.production_healing_suite_pack_drill import (
    run_production_healing_suite_pack_drill,
)


def _pass(**_kwargs):
    return {"ok": True}


def test_a_healing_pack_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.multi_app_healing_suite_drill as multi
    import backend.production_healing_flaky_policy_drill as flaky
    import backend.production_healing_readiness_drill as ready
    import backend.production_healing_replay_pack_drill as replay
    import backend.production_healing_taxonomy_drill as taxonomy

    secret = "tenant-b-heal-pack"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "production_healing_suite_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_production_healing_suite_pack_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_e_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_production_healing_suite_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()

    monkeypatch.setattr(ready, "run_production_healing_readiness_drill", _pass)
    monkeypatch.setattr(flaky, "run_production_healing_flaky_policy_drill", _pass)
    monkeypatch.setattr(replay, "run_production_healing_replay_pack_drill", _pass)
    monkeypatch.setattr(taxonomy, "run_production_healing_taxonomy_drill", _pass)
    monkeypatch.setattr(multi, "run_multi_app_healing_suite_drill", _pass)
    planted.unlink()
    saved = run_production_healing_suite_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_e_complete"] is False
    assert saved["production_suite_executed"] is False
    assert saved["ok"] is True
    assert saved["parts"]["readiness"] is True
    assert "suite pack ok" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_heal_pack_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-heal-pack-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-heal-pack-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "E")["status"] != "done"
    assert snap["complete"] is False
