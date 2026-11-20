"""A review pack writes this install's receipt. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.independent_review_pack_drill import run_independent_review_pack_drill


def test_a_review_pack_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.independent_review_pack_drill as mod

    calls = {"n": 0}
    real_sha = mod.hashlib.sha256

    def _sha256(data=b""):
        calls["n"] += 1
        return real_sha(data)

    monkeypatch.setattr(mod.hashlib, "sha256", _sha256)

    secret = "tenant-b-only-pack"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "independent_review_pack.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_independent_review_pack_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert [path.name for path in other.iterdir()] == ["independent_review_pack.json"]

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "independent_review_pack.json"
    planted.symlink_to(kept)
    skipped = run_independent_review_pack_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    origin = mod.CHECKLIST
    note = other / "secret-checklist.md"
    note.write_text(secret, encoding="utf-8")
    linked_list = tmp_path / "checklist.md"
    linked_list.symlink_to(note)
    monkeypatch.setattr(mod, "CHECKLIST", linked_list)
    unread = run_independent_review_pack_drill(ops_dir=folder)
    assert unread["checklist_present"] is False
    assert unread["ok"] is False
    assert unread["signed_off"] is False
    assert secret not in str(unread)
    assert note.read_text(encoding="utf-8") == secret
    monkeypatch.setattr(mod, "CHECKLIST", origin)

    saved = run_independent_review_pack_drill(ops_dir=folder)
    written = (folder / "independent_review_pack.json").read_text(encoding="utf-8")
    assert calls["n"] >= 1
    assert saved["ok"] is True
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert saved["artifact_count"] > 0
    assert secret not in written
    assert kept.read_bytes() == original


def test_pack_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-pack-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
