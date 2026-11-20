"""A multi-API matrix uses this install's API levels. A link is left unread."""
import json

from backend.blueprint_progress import progress
from backend.multi_api_android_matrix_drill import run_multi_api_android_matrix_drill


def test_a_multi_api_matrix_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.multi_api_android_matrix_drill as mod

    calls = {"n": 0}
    real_load = mod._load

    def _load(name):
        calls["n"] += 1
        return real_load(name)

    monkeypatch.setattr(mod, "_load", _load)

    secret = "tenant-b-api-level"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "multi_api_android_matrix_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_multi_api_android_matrix_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_d_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    install = tmp_path / "install"
    evidence_dir = install / "docs" / "ops-evidence"
    evidence_dir.mkdir(parents=True)
    secret_smoke = other / "secret-smoke.json"
    secret_smoke.write_text(
        json.dumps({
            "ok": True,
            "api_level": 777,
            "note": secret,
            "matrix_rows": [{"api_level": 777, "outcome": "passed", "note": secret}],
        }),
        encoding="utf-8",
    )
    smoke = evidence_dir / "android_emulator_smoke_api24_drill.json"
    smoke.symlink_to(secret_smoke)
    monkeypatch.setattr(mod, "ROOT", install)
    real = tmp_path / "real"
    real.mkdir()
    planted = real / kept.name
    planted.symlink_to(kept)
    skipped_file = run_multi_api_android_matrix_drill(ops_dir=real)
    assert skipped_file["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped_file)
    assert kept.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    skipped = run_multi_api_android_matrix_drill(ops_dir=real)
    written = (real / kept.name).read_text(encoding="utf-8")
    assert skipped["gate_d_complete"] is False
    assert skipped["ok"] is False
    assert skipped["rows"] == 0
    assert calls["n"] == 4
    assert 777 not in (skipped["api_levels"] or [])
    assert secret not in written
    assert kept.read_bytes() == original

    smoke.unlink()
    smoke.write_text(
        json.dumps({
            "ok": True,
            "api_level": 24,
            "matrix_rows": [{"api_level": "24", "outcome": "passed", "source": "this-install"}],
        }),
        encoding="utf-8",
    )
    saved = run_multi_api_android_matrix_drill(ops_dir=real)
    saved_text = (real / kept.name).read_text(encoding="utf-8")
    assert saved["gate_d_complete"] is False
    assert saved["rows"] == 1
    assert calls["n"] == 8
    assert 24 in saved["api_levels"]
    assert 777 not in saved["api_levels"]
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_multi_api_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-multi-api-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-multi-api-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "D")["status"] != "done"
    assert snap["complete"] is False
