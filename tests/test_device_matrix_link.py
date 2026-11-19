"""A device matrix uses this install's rows. A link is left unread."""
import json

from backend.blueprint_progress import progress
from backend.device_matrix_drill import run_device_matrix_drill


def test_a_device_matrix_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.device_matrix_drill as mod

    secret = "tenant-b-device-row"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "device_matrix_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_device_matrix_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    install = tmp_path / "install"
    evidence_dir = install / "docs" / "ops-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "device_matrix_evidence.json").write_text(
        json.dumps([{
            "surface": "web",
            "viewport": "1366x900",
            "outcome": "passed",
            "source": "this-install",
        }]),
        encoding="utf-8",
    )
    secret_rows = other / "secret-rows.json"
    secret_rows.write_text(
        json.dumps([{"surface": "android", "outcome": "passed", "note": secret}]),
        encoding="utf-8",
    )
    live = evidence_dir / "android_live_matrix_rows.json"
    live.symlink_to(secret_rows)
    monkeypatch.setattr(mod, "ROOT", install)
    real = tmp_path / "real"
    real.mkdir()
    skipped = run_device_matrix_drill(ops_dir=real)
    written = (real / kept.name).read_text(encoding="utf-8")
    assert skipped["gate_d_complete"] is False
    assert skipped["ok"] is True
    assert skipped["web_rows"] == 1
    assert skipped["android_live_rows"] == 0
    assert secret not in written
    assert kept.read_bytes() == original

    live.unlink()
    live.write_text(
        json.dumps([{
            "surface": "android",
            "device_id": "this-install-device",
            "outcome": "passed",
            "source": "android_live",
        }]),
        encoding="utf-8",
    )
    saved = run_device_matrix_drill(ops_dir=real)
    saved_text = (real / kept.name).read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["ok"] is True
    assert saved["web_rows"] == 1
    assert saved["android_live_rows"] == 1
    assert '"android_live_rows": 1' in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_device_matrix_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-device-matrix-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-device-matrix-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert snap["complete"] is False
