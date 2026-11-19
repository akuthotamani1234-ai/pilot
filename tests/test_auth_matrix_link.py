"""A dashboard auth drill writes this install's matrix. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.dashboard_auth_matrix_drill import run_dashboard_auth_matrix_drill


def test_a_dashboard_auth_drill_does_not_follow_a_link_into_another_folder(tmp_path):
    secret = "tenant-b-only-auth"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "keep.txt"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = run_dashboard_auth_matrix_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_i_complete"] is False
    assert kept.read_bytes() == original
    assert secret not in evidence["reason"]
    assert not (other / "dashboard_auth_work").exists()
    assert not (other / "dashboard_auth_matrix_drill.json").exists()

    real = tmp_path / "real"
    real.mkdir()
    saved = run_dashboard_auth_matrix_drill(ops_dir=real)
    written = (real / "dashboard_auth_matrix_drill.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_i_complete"] is False
    assert set(saved["modes_covered"]) == {"none", "bearer", "webhook", "principal", "oidc"}
    assert secret not in written
    assert kept.read_bytes() == original


def test_auth_matrix_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-auth-matrix-link")
    assert row["status"] == "done"
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-findings-template-link") == 1
    assert ids.count("G-findings-link") == 1
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "I")["status"] != "done"
    assert snap["complete"] is False
