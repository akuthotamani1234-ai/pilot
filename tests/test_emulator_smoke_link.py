"""An emulator smoke drill uses this install's rows. A link is left unread."""
import json

from backend.android_emulator_smoke_drill import run_android_emulator_smoke_drill
from backend.blueprint_progress import progress


def test_an_emulator_smoke_drill_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.android_emulator_smoke_drill as mod

    secret = "tenant-b-emulator"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "android_emulator_smoke_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_android_emulator_smoke_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    install = tmp_path / "install"
    evidence_dir = install / "docs" / "ops-evidence"
    evidence_dir.mkdir(parents=True)
    secret_rows = other / "secret-rows.json"
    secret_rows.write_text(
        json.dumps([{"device_id": secret, "source": "android_emulator_smoke", "api_level": 99}]),
        encoding="utf-8",
    )
    rows_original = secret_rows.read_bytes()
    live = evidence_dir / "android_live_matrix_rows.json"
    live.symlink_to(secret_rows)
    monkeypatch.setattr(mod, "ROOT", install)
    monkeypatch.setattr(mod, "EVIDENCE", evidence_dir / kept.name)
    skipped = run_android_emulator_smoke_drill()
    written = (evidence_dir / kept.name).read_text(encoding="utf-8")
    assert skipped["gate_d_complete"] is False
    assert secret not in written
    assert secret not in str(skipped)
    assert secret_rows.read_bytes() == rows_original
    assert kept.read_bytes() == original

    live.unlink()
    token = "this-install-emulator"
    live.write_text(
        json.dumps([{"device_id": token, "source": "android_emulator_smoke", "api_level": 24}]),
        encoding="utf-8",
    )
    saved = run_android_emulator_smoke_drill()
    saved_rows = live.read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert token in saved_rows
    assert secret not in saved_rows
    assert secret not in (evidence_dir / kept.name).read_text(encoding="utf-8")
    assert secret_rows.read_bytes() == rows_original


def test_emulator_smoke_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-emulator-smoke-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-emulator-smoke-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert snap["complete"] is False
