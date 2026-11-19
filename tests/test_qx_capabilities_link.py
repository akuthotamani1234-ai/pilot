"""A capability drill uses this install's pages. A link is left unread."""
import json

from backend.blueprint_progress import progress
from backend.qx_capabilities_drill import run_qx_capabilities_drill


def test_a_capability_drill_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.qx_capabilities_drill as mod

    secret = "tenant-b-only-page"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "qx_capabilities_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_qx_capabilities_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    install = tmp_path / "install"
    coverage = install / "docs" / "ops-evidence" / "demo_store_surface_coverage.json"
    coverage.parent.mkdir(parents=True)
    secret_pages = other / "secret-coverage.json"
    secret_pages.write_text(
        json.dumps({"pages_walked": [secret]}),
        encoding="utf-8",
    )
    coverage.symlink_to(secret_pages)
    monkeypatch.setattr(mod, "ROOT", install)
    real = tmp_path / "real"
    real.mkdir()
    skipped = run_qx_capabilities_drill(ops_dir=real)
    written = (real / kept.name).read_text(encoding="utf-8")
    assert skipped["gate_complete"] is False
    assert secret not in written
    assert f"/{secret}" not in written
    assert kept.read_bytes() == original

    coverage.unlink()
    token = "this-install-page"
    coverage.write_text(
        json.dumps({"pages_walked": ["/", "about", token]}),
        encoding="utf-8",
    )
    saved = run_qx_capabilities_drill(ops_dir=real)
    saved_text = (real / kept.name).read_text(encoding="utf-8")
    assert saved["gate_complete"] is False
    assert saved["ok"] is True
    assert f"/{token}" in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_qx_capabilities_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-qx-capabilities-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-qx-capabilities-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "A")["status"] != "done"
    assert snap["complete"] is False
