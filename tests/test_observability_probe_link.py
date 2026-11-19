"""An observability probe uses this install's evidence names. A link is left unread."""
from backend.blueprint_progress import progress
from backend.observability_probe_drill import run_observability_probe_drill


def test_an_observability_probe_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.observability_probe_drill as mod

    secret = "tenant-b-metric"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "observability_probe_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_observability_probe_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_h_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    secret_dir = other / "evidence"
    secret_dir.mkdir()
    (secret_dir / f"{secret}.json").write_text(secret, encoding="utf-8")
    linked_evidence = tmp_path / "linked-evidence"
    linked_evidence.symlink_to(secret_dir, target_is_directory=True)
    monkeypatch.setattr(mod, "OPS_EVIDENCE", linked_evidence)
    real = tmp_path / "real"
    real.mkdir()
    skipped = run_observability_probe_drill(ops_dir=real)
    written = (real / kept.name).read_text(encoding="utf-8")
    assert skipped["gate_h_complete"] is False
    assert skipped["evidence_artifacts"] == 0
    assert secret not in written
    assert kept.read_bytes() == original

    install = tmp_path / "install-evidence"
    install.mkdir()
    token = "aaa-this-install-probe"
    (install / f"{token}.json").write_text("{}", encoding="utf-8")
    (install / "linked.json").symlink_to(secret_dir / f"{secret}.json")
    monkeypatch.setattr(mod, "OPS_EVIDENCE", install)
    saved = run_observability_probe_drill(ops_dir=real)
    saved_text = (real / kept.name).read_text(encoding="utf-8")
    assert saved["gate_h_complete"] is False
    assert saved["ok"] is True
    assert saved["evidence_artifacts"] == 1
    assert token in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_observability_probe_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-observability-probe-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-observability-probe-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "H")["status"] != "done"
    assert snap["complete"] is False
