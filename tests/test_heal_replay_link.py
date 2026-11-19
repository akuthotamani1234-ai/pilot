"""A healing replay pack stays in this install. A link does not start the bundled checks."""
from backend.blueprint_progress import progress
from backend.production_healing_replay_pack_drill import (
    run_production_healing_replay_pack_drill,
)


def test_a_healing_replay_pack_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.multi_app_healing_suite_drill as suite
    import backend.production_healing_contract_drill as contract
    import backend.production_healing_replay_pack_drill as mod

    calls = {"n": 0}

    def _child(**_kwargs):
        calls["n"] += 1
        return {"ok": True}

    def _review(_before, after):
        calls["n"] += 1
        return {"allowed": "assert True" not in after}

    monkeypatch.setattr(suite, "run_multi_app_healing_suite_drill", _child)
    monkeypatch.setattr(contract, "run_production_healing_contract_drill", _child)
    monkeypatch.setattr(mod, "review_repair", _review)

    secret = "tenant-b-replay"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "production_healing_replay_pack_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_production_healing_replay_pack_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_e_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_production_healing_replay_pack_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_production_healing_replay_pack_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_e_complete"] is False
    assert saved["ok"] is True
    assert saved["passed"] == 4
    assert calls["n"] == 10
    assert "replay pack" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_heal_replay_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-heal-replay-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-heal-replay-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "E")["status"] != "done"
    assert snap["complete"] is False
