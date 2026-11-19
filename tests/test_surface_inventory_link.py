"""A surface inventory writes this install's pages. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.surface_evidence_drill import (
    run_admin_portal_surface_drill,
    run_classic_shop_surface_drill,
    run_demo_store_surface_drill,
    run_travel_site_surface_drill,
)


def test_a_surface_inventory_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    from tests.admin_portal import AdminPortal
    from tests.classic_shop import ClassicShop
    from tests.demo_store import DemoStore
    from tests.travel_site import TravelSite

    calls = {"n": 0}

    def _count(cls):
        real_start = cls.start

        def start(self, *args, **kwargs):
            calls["n"] += 1
            return real_start(self, *args, **kwargs)

        monkeypatch.setattr(cls, "start", start)

    for cls in (AdminPortal, ClassicShop, DemoStore, TravelSite):
        _count(cls)

    secret = "tenant-b-only-surface-inventory"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "admin_portal_surface_coverage.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = [
        run_admin_portal_surface_drill(ops_dir=linked),
        run_demo_store_surface_drill(ops_dir=linked),
        run_classic_shop_surface_drill(ops_dir=linked),
        run_travel_site_surface_drill(ops_dir=linked),
    ]
    for evidence in refused:
        assert "link" in evidence["reason"]
        assert evidence["ok"] is False
        assert evidence["gate_a_surfaces_complete"] is False
        assert secret not in str(evidence)
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == ["admin_portal_surface_coverage.json"]

    folder = tmp_path / "real"
    folder.mkdir()
    names = (
        "admin_portal_surface_coverage.json",
        "demo_store_surface_coverage.json",
        "classic_shop_surface_coverage.json",
        "travel_site_surface_coverage.json",
    )
    planted = [folder / name for name in names]
    for path in planted:
        path.symlink_to(kept)
    skipped = [
        run_admin_portal_surface_drill(ops_dir=folder),
        run_demo_store_surface_drill(ops_dir=folder),
        run_classic_shop_surface_drill(ops_dir=folder),
        run_travel_site_surface_drill(ops_dir=folder),
    ]
    for evidence in skipped:
        assert evidence["ok"] is False
        assert secret not in str(evidence)
    assert calls["n"] == 0
    assert kept.read_bytes() == original
    assert all(path.is_symlink() for path in planted)
    for path in planted:
        path.unlink()

    saved = run_admin_portal_surface_drill(ops_dir=folder)
    written = (folder / "admin_portal_surface_coverage.json").read_text(encoding="utf-8")
    assert calls["n"] == 1
    assert saved["gate_a_surfaces_complete"] is False
    assert "users" in saved["pages_walked"]
    assert secret not in written
    assert kept.read_bytes() == original


def test_surface_inventory_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-surface-inventory-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "A")["status"] != "done"
    assert snap["complete"] is False
