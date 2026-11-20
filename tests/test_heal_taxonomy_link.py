"""A failure taxonomy stays in this install. A link does not start the classification."""
from backend.blueprint_progress import progress
from backend.production_healing_taxonomy_drill import (
    run_production_healing_taxonomy_drill,
)


def test_a_failure_taxonomy_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.production_healing_taxonomy_drill as mod

    calls = {"n": 0}
    real_review = mod.review_repair
    real_classify = mod.classify

    def _blocked(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("classification started")

    monkeypatch.setattr(mod, "review_repair", _blocked)
    monkeypatch.setattr(mod, "classify", _blocked)

    secret = "tenant-b-taxonomy"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "production_healing_taxonomy_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_production_healing_taxonomy_drill(ops_dir=linked)
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
    skipped = run_production_healing_taxonomy_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "production_healing_matrix_drill.json").write_text(secret, encoding="utf-8")
    linked_root = tmp_path / "linked-root"
    (linked_root / "docs").mkdir(parents=True)
    (linked_root / "docs" / "ops-evidence").symlink_to(foreign, target_is_directory=True)
    monkeypatch.setattr(mod, "ROOT", linked_root)
    monkeypatch.setattr(mod, "review_repair", real_review)
    monkeypatch.setattr(mod, "classify", real_classify)
    unread = run_production_healing_taxonomy_drill(ops_dir=real)
    assert unread["live_matrix_present"] is False
    assert unread["matched"] == 6
    assert secret not in str(unread)
    assert secret not in planted.read_text(encoding="utf-8")
    assert (foreign / "production_healing_matrix_drill.json").read_text(encoding="utf-8") == secret

    real_root = tmp_path / "real-root"
    ops = real_root / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    (ops / "production_healing_matrix_drill.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", real_root)
    saved = run_production_healing_taxonomy_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_e_complete"] is False
    assert saved["ok"] is True
    assert saved["healing"]["weaken_denied"] is True
    assert saved["matched"] == 6
    assert "healing taxonomy" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_heal_taxonomy_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-heal-taxonomy-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-heal-taxonomy-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "E")["status"] != "done"
    assert snap["complete"] is False
