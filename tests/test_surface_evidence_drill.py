"""Gate A fixture surface drills stay incomplete and inventory expected signals."""
from pathlib import Path

from backend.surface_evidence_drill import (
    run_admin_portal_surface_drill,
    run_classic_shop_surface_drill,
    run_demo_store_surface_drill,
    run_travel_site_surface_drill,
)


def test_admin_portal_surface_drill_records_rich_controls(tmp_path: Path):
    evidence = run_admin_portal_surface_drill(ops_dir=tmp_path)
    assert evidence["gate_a_surfaces_complete"] is False
    assert "users" in evidence["pages_walked"]
    rich = evidence["surfaces"]["rich_controls"]
    assert rich["file_upload"] + rich["web_component"] + rich["canvas"] >= 1
    assert (tmp_path / "admin_portal_surface_coverage.json").is_file()


def test_demo_store_surface_drill_sees_lab_iframe_shadow(tmp_path: Path):
    evidence = run_demo_store_surface_drill(ops_dir=tmp_path)
    assert evidence["gate_a_surfaces_complete"] is False
    assert "lab" in evidence["pages_walked"]
    assert evidence["surfaces"]["frames"]["pages_with_frames"] >= 1
    assert evidence["surfaces"]["shadow"]["pages_with_shadow"] >= 1
    assert evidence["surfaces"]["rich_controls"]["canvas"] >= 1
    lazy = (evidence["surfaces"].get("evidence") or {}).get("lazy") or {}
    assert int(lazy.get("pages_with_lazy") or 0) >= 1
    assert (tmp_path / "demo_store_surface_coverage.json").is_file()


def test_classic_and_travel_surface_drills(tmp_path: Path):
    classic = run_classic_shop_surface_drill(ops_dir=tmp_path)
    assert classic["gate_a_surfaces_complete"] is False
    assert classic["surfaces"]["pages"] >= 3
    travel = run_travel_site_surface_drill(ops_dir=tmp_path)
    assert travel["gate_a_surfaces_complete"] is False
    assert "signup" in travel["pages_walked"]
    assert (tmp_path / "classic_shop_surface_coverage.json").is_file()
    assert (tmp_path / "travel_site_surface_coverage.json").is_file()
