"""Gate A AdminPortal surface inventory drill stays incomplete."""
from pathlib import Path

from backend.surface_evidence_drill import run_admin_portal_surface_drill


def test_admin_portal_surface_drill(tmp_path: Path):
    evidence = run_admin_portal_surface_drill(ops_dir=tmp_path)
    assert evidence["gate_a_surfaces_complete"] is False
    assert evidence["drill"] == "admin_portal_surface_coverage"
    assert len(evidence["pages_walked"]) >= 5
    surfaces = evidence["surfaces"]
    assert surfaces["gate_a_surfaces_complete"] is False
    assert surfaces["pages"] >= 5
    # AdminPortal widgets/reports expose shadow and/or iframes on a healthy run.
    frames = surfaces["frames"]["listed_iframes"]
    shadow = surfaces["shadow"]["open_roots_seen"]
    dialogs = surfaces["dialogs"]["pages_with_dialogs"]
    downloads = surfaces["downloads"]["links"]
    assert frames + shadow + dialogs + downloads >= 1
    assert (tmp_path / "admin_portal_surface_coverage.json").is_file()
