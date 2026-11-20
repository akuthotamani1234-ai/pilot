"""An audit export stays in this install. A link does not open the audit database."""
from backend.audit_export_drill import run_audit_export_drill
from backend.blueprint_progress import progress


def test_an_audit_export_does_not_follow_a_link(tmp_path, monkeypatch):
    import backend.audit_export_drill as mod

    calls = {"n": 0}
    real_record = mod.record_audit

    def _record(*args, **kwargs):
        calls["n"] += 1
        return real_record(*args, **kwargs)

    monkeypatch.setattr(mod, "record_audit", _record)

    secret = "tenant-b-audit"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "audit_export_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_audit_export_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_g_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_audit_export_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    work = real / "audit_export_work"
    work.symlink_to(other, target_is_directory=True)
    unread = run_audit_export_drill(ops_dir=real)
    assert unread["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(unread)
    assert not (other / "audit.sqlite").exists()
    assert kept.read_bytes() == original
    work.unlink()

    saved = run_audit_export_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_g_complete"] is False
    assert saved["ok"] is True
    assert saved["scoped_count"] == 2
    assert saved["scoped_tenants"] == ["t-a"]
    assert calls["n"] == 3
    assert "audit export" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_audit_export_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-audit-export-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-audit-export-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
