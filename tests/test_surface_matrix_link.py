"""A surface matrix reads this install's inventories. A link is left untouched."""
import json

from backend.blueprint_progress import progress
from backend.discovery_surface_matrix_drill import run_discovery_surface_matrix_drill


def test_a_surface_matrix_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.surface_evidence_drill as surfaces

    calls = {"n": 0}
    for name in (
        "run_admin_portal_surface_drill",
        "run_demo_store_surface_drill",
        "run_classic_shop_surface_drill",
        "run_travel_site_surface_drill",
    ):
        real = getattr(surfaces, name)

        def _wrap(fn):
            def _inner(*args, **kwargs):
                calls["n"] += 1
                return fn(*args, **kwargs)
            return _inner

        monkeypatch.setattr(surfaces, name, _wrap(real))

    secret = "tenant-b-only-surface"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "admin_portal_surface_coverage.json"
    kept.write_text(json.dumps({
        "pages_walked": ["/", secret],
    }), encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_discovery_surface_matrix_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_a_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(evidence)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == ["admin_portal_surface_coverage.json"]

    real = tmp_path / "real"
    real.mkdir()
    planted = real / "discovery_surface_matrix_drill.json"
    planted.symlink_to(kept)
    skipped = run_discovery_surface_matrix_drill(ops_dir=real)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    saved = run_discovery_surface_matrix_drill(ops_dir=real)
    written = (real / "discovery_surface_matrix_drill.json").read_text(encoding="utf-8")
    assert saved["gate_a_complete"] is False
    assert saved["total"] == 4
    assert saved["union_of"] == 11
    assert calls["n"] == 4
    assert secret not in written
    assert kept.read_bytes() == original


def test_surface_matrix_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-surface-matrix-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "A")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
