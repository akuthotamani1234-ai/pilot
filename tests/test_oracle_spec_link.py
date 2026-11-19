"""A DemoStore oracle reads this install's fixture. A link is left unread."""
import json

import backend.oracle_spec_drill as drill
from backend.blueprint_progress import progress


def test_a_demostore_oracle_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-oracle-spec"
    other = tmp_path / "other"
    other.mkdir()
    secret_file = other / "secret.json"
    secret_file.write_text(json.dumps({
        "features": [{"id": secret, "test": secret, "page": "/secret"}],
    }), encoding="utf-8")
    original = secret_file.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = drill.run_oracle_spec_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_c_complete"] is False
    assert secret not in str(evidence)
    assert secret_file.read_bytes() == original
    assert [path.name for path in other.iterdir()] == ["secret.json"]

    real = tmp_path / "real"
    real.mkdir()
    linked_truth = real / "linked-truth.json"
    linked_truth.symlink_to(secret_file)
    monkeypatch.setattr(drill, "TRUTH", linked_truth)
    leaked = drill.run_oracle_spec_drill(ops_dir=real)
    assert leaked["ok"] is False
    assert leaked["gate_c_complete"] is False
    assert secret not in str(leaked)
    assert secret_file.read_bytes() == original
    assert not (real / "oracle_spec_drill.json").exists()

    truth = real / "truth.json"
    truth.write_text(json.dumps({
        "features": [{"id": "this-install-feature", "test": "visible", "page": "/"}],
    }), encoding="utf-8")
    monkeypatch.setattr(drill, "TRUTH", truth)
    saved = drill.run_oracle_spec_drill(ops_dir=real)
    written = (real / "oracle_spec_drill.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_c_complete"] is False
    assert saved["features_bound"] >= 1
    assert "this-install-feature" in written
    assert secret not in written
    assert secret_file.read_bytes() == original


def test_oracle_spec_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-oracle-spec-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "C")["status"] != "done"
    assert snap["complete"] is False
