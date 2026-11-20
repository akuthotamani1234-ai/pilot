"""An incident tabletop stays in this install. A link is not read or written."""
from backend.blueprint_progress import progress
from backend.incident_tabletop_drill import run_incident_tabletop_drill


def test_an_incident_tabletop_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.incident_tabletop_drill as mod

    calls = {"n": 0}
    real_has = mod._has
    real_root = mod.ROOT
    real_runbook = mod.RUNBOOK

    def _has(name):
        calls["n"] += 1
        return real_has(name)

    monkeypatch.setattr(mod, "_has", _has)

    secret = "tenant-b-tabletop"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "incident_tabletop_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_incident_tabletop_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_incident_tabletop_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    fake = tmp_path / "root"
    (fake / "docs" / "ops-evidence").mkdir(parents=True)
    (fake / "docs" / "INCIDENT_RUNBOOK.md").symlink_to(kept)
    (fake / "docs" / "ops-evidence" / "backup_restore_drill.json").symlink_to(kept)
    monkeypatch.setattr(mod, "ROOT", fake)
    monkeypatch.setattr(mod, "RUNBOOK", fake / "docs" / "INCIDENT_RUNBOOK.md")
    unread = run_incident_tabletop_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert unread["runbook_present"] is False
    assert calls["n"] == 3
    assert secret not in str(unread)
    assert secret not in saved_text
    assert kept.read_bytes() == original

    monkeypatch.setattr(mod, "ROOT", real_root)
    monkeypatch.setattr(mod, "RUNBOOK", real_runbook)
    saved = run_incident_tabletop_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["ok"] is True
    assert saved["runbook_present"] is True
    assert calls["n"] == 6
    assert "incident tabletop" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_tabletop_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-tabletop-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-tabletop-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
