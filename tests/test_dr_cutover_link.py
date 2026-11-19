"""A cutover checklist stays in this install. A link is left unread."""
from backend.blueprint_progress import progress
from backend.hosted_dr_cutover_checklist_drill import (
    CHECKLIST,
    run_hosted_dr_cutover_checklist_drill,
)


def test_a_cutover_checklist_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.hosted_dr_cutover_checklist_drill as mod

    secret = "tenant-b-cutover"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "hosted_dr_cutover_checklist_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_hosted_dr_cutover_checklist_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_hosted_dr_cutover_checklist_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / CHECKLIST[0][1]).write_text(secret, encoding="utf-8")
    linked_root = tmp_path / "linked-root"
    (linked_root / "docs").mkdir(parents=True)
    (linked_root / "docs" / "ops-evidence").symlink_to(foreign, target_is_directory=True)
    monkeypatch.setattr(mod, "ROOT", linked_root)
    unread = run_hosted_dr_cutover_checklist_drill(ops_dir=real)
    assert unread["ok"] is False
    assert unread["score"] == 0
    assert secret not in str(unread)
    assert secret not in planted.read_text(encoding="utf-8")
    assert (foreign / CHECKLIST[0][1]).read_text(encoding="utf-8") == secret

    real_root = tmp_path / "real-root"
    ops = real_root / "docs" / "ops-evidence"
    ops.mkdir(parents=True)
    for _key, artifact, _label in CHECKLIST:
        (ops / artifact).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", real_root)
    saved = run_hosted_dr_cutover_checklist_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["live_hosted_dr"] is False
    assert saved["ok"] is True
    assert saved["score"] == len(CHECKLIST)
    assert "cutover checklist" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_dr_cutover_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-dr-cutover-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-dr-cutover-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
