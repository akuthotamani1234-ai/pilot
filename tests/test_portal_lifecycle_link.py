"""An admin portal cleanup stays in this install. A link does not start the portal."""
from backend.admin_portal_lifecycle_drill import run_admin_portal_lifecycle_drill
from backend.blueprint_progress import progress


def test_an_admin_portal_cleanup_does_not_follow_a_link(tmp_path, monkeypatch):
    import tests.admin_portal as portal_mod

    calls = {"n": 0}
    real_portal = portal_mod.AdminPortal

    class _Counting:
        def __init__(self):
            self._inner = real_portal()

        def start(self):
            calls["n"] += 1
            return self._inner.start()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(portal_mod, "AdminPortal", _Counting)

    secret = "tenant-b-portal"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "admin_portal_lifecycle_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_admin_portal_lifecycle_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_c_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped = run_admin_portal_lifecycle_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    work = real / "admin_portal_lifecycle_work"
    work.symlink_to(other, target_is_directory=True)
    unread = run_admin_portal_lifecycle_drill(ops_dir=real)
    assert unread["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(unread)
    assert not any(path.name.startswith("run_") for path in other.iterdir())
    assert kept.read_bytes() == original
    work.unlink()

    saved = run_admin_portal_lifecycle_drill(ops_dir=real)
    saved_text = planted.read_text(encoding="utf-8")
    assert saved["gate_c_complete"] is False
    assert saved["ok"] is True
    assert saved["user_removed"] is True
    assert calls["n"] == 1
    assert "AdminPortal" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_portal_lifecycle_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-portal-lifecycle-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-portal-lifecycle-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "C")["status"] != "done"
    assert snap["complete"] is False
