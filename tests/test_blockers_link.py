"""A blocker inventory writes this install's list. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.remaining_blockers_drill import run_remaining_blockers_drill


def test_a_blocker_inventory_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.remaining_blockers_drill as mod

    origin = mod.ROOT
    secret = "tenant-b-only-blockers"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "remaining_blockers.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_remaining_blockers_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["complete"] is False
    assert evidence["open_count"] == 6
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == ["remaining_blockers.json"]

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "remaining_blockers.json"
    planted.symlink_to(kept)
    fake = tmp_path / "evidence-root"
    ops = fake / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    secret_note = other / "secret-note.json"
    secret_note.write_text(secret, encoding="utf-8")
    (ops / "multi_region_dr_drill.json").symlink_to(secret_note)
    monkeypatch.setattr(mod, "ROOT", fake)
    skipped = run_remaining_blockers_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    scanned = run_remaining_blockers_drill(ops_dir=folder)
    present = scanned["blockers"][0]["local_partial_present"]
    assert "multi_region_dr_drill.json" not in present
    assert secret not in str(scanned)
    assert secret_note.read_text(encoding="utf-8") == secret
    monkeypatch.setattr(mod, "ROOT", origin)

    saved = run_remaining_blockers_drill(ops_dir=folder)
    written = (folder / "remaining_blockers.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["complete"] is False
    assert saved["open_count"] == 6
    assert secret not in written
    assert kept.read_bytes() == original


def test_blockers_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-blockers-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
    assert snap["counts"]["blockers_open"] >= 6
