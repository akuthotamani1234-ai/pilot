"""A swarm checklist stays in this install. A link is left unread."""
from backend.blueprint_progress import progress
from backend.swarm_review_checklist_drill import (
    POINTERS,
    run_swarm_review_checklist_drill,
)


def test_a_swarm_checklist_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.swarm_review_checklist_drill as mod

    secret = "tenant-b-swarm"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "swarm_review_checklist.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    foreign = tmp_path / "foreign.md"
    foreign.write_text(secret, encoding="utf-8")
    linked_doc = tmp_path / "checklist.md"
    linked_doc.symlink_to(foreign)
    monkeypatch.setattr(mod, "CHECKLIST", linked_doc)
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_swarm_review_checklist_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_b_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert foreign.read_text(encoding="utf-8") == secret
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_swarm_review_checklist_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    foreign_ops = tmp_path / "foreign-ops"
    foreign_ops.mkdir()
    (foreign_ops / POINTERS[0]).write_text(secret, encoding="utf-8")
    linked_root = tmp_path / "linked-root"
    (linked_root / "docs").mkdir(parents=True)
    (linked_root / "docs" / "ops-evidence").symlink_to(foreign_ops, target_is_directory=True)
    monkeypatch.setattr(mod, "ROOT", linked_root)
    unread = run_swarm_review_checklist_drill(ops_dir=real)
    assert unread["ok"] is False
    assert unread["checklist_present"] is False
    assert unread["evidence_pointers_present"] == []
    assert secret not in str(unread)
    assert secret not in planted.read_text(encoding="utf-8")
    assert (foreign_ops / POINTERS[0]).read_text(encoding="utf-8") == secret

    real_root = tmp_path / "real-root"
    ops = real_root / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for name in POINTERS[:4]:
        (ops / name).write_text("{}", encoding="utf-8")
    checklist = real_root / "checklist.md"
    checklist.write_text("# checklist\n", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", real_root)
    monkeypatch.setattr(mod, "CHECKLIST", checklist)
    saved = run_swarm_review_checklist_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_b_complete"] is False
    assert saved["signed_off"] is False
    assert saved["ok"] is True
    assert saved["checklist_present"] is True
    assert "checklist published" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_swarm_check_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-swarm-check-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-swarm-check-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "B")["status"] != "done"
    assert snap["complete"] is False
