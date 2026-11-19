"""A surface inventory writes this install's pages. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.surface_evidence_drill import (
    run_admin_portal_surface_drill,
    run_classic_shop_surface_drill,
    run_demo_store_surface_drill,
    run_travel_site_surface_drill,
)


def test_a_surface_inventory_does_not_follow_a_link_into_another_folder(tmp_path):
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
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == ["admin_portal_surface_coverage.json"]

    real = tmp_path / "real"
    real.mkdir()
    saved = run_admin_portal_surface_drill(ops_dir=real)
    written = (real / "admin_portal_surface_coverage.json").read_text(encoding="utf-8")
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
