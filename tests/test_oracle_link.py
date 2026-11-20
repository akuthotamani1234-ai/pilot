"""A portal oracle reads this install's fixtures. A link is left unread."""
import json

import backend.multi_portal_oracle_drill as drill
from backend.blueprint_progress import progress


def test_a_portal_oracle_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    calls = {"n": 0}
    real_bind = drill._bind_portal

    def _bind_portal(name, path):
        calls["n"] += 1
        return real_bind(name, path)

    monkeypatch.setattr(drill, "_bind_portal", _bind_portal)

    secret = "tenant-b-only-oracle"
    other = tmp_path / "other"
    other.mkdir()
    secret_file = other / "secret.json"
    secret_file.write_text(json.dumps({
        "features": [{"id": secret, "test": secret, "page": "/secret"}],
    }), encoding="utf-8")
    original = secret_file.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = drill.run_multi_portal_oracle_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_c_complete"] is False
    assert calls["n"] == 0
    assert secret not in str(evidence)
    assert secret_file.read_bytes() == original
    assert [path.name for path in other.iterdir()] == ["secret.json"]

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "multi_portal_oracle_drill.json"
    planted.symlink_to(secret_file)
    skipped = drill.run_multi_portal_oracle_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert secret_file.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    truth = folder / "truth.json"
    truth.write_text(json.dumps({
        "features": [{"id": "this-install-feature", "test": "visible", "page": "/"}],
    }), encoding="utf-8")
    linked_truth = folder / "linked-truth.json"
    linked_truth.symlink_to(secret_file)
    monkeypatch.setattr(drill, "PORTALS", (
        ("Leaked", linked_truth),
        ("Ours", truth),
    ))
    saved = drill.run_multi_portal_oracle_drill(ops_dir=folder)
    written = (folder / "multi_portal_oracle_drill.json").read_text(encoding="utf-8")
    assert calls["n"] == 2
    assert saved["gate_c_complete"] is False
    assert "this-install-feature" in written
    assert secret not in written
    assert secret_file.read_bytes() == original


def test_oracle_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-oracle-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "C")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
