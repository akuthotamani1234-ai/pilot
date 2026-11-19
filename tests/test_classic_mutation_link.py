"""A ClassicShop mutation score reads this install's fixture. A link is left unread."""
import json

import backend.classic_mutation_score_drill as drill
from backend.blueprint_progress import progress


def test_a_classic_mutation_score_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-classic"
    other = tmp_path / "other"
    other.mkdir()
    secret_file = other / "secret.json"
    secret_file.write_text(json.dumps({
        "bugs": {secret: {}},
        "buggy": {"bugs": {"caught": [secret]}},
    }), encoding="utf-8")
    original = secret_file.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = drill.run_classic_mutation_score_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_j_complete"] is False
    assert secret not in str(evidence)
    assert secret_file.read_bytes() == original
    assert [path.name for path in other.iterdir()] == ["secret.json"]

    real = tmp_path / "real"
    real.mkdir()
    linked_truth = real / "linked-truth.json"
    linked_truth.symlink_to(secret_file)
    linked_summary = real / "linked-summary.json"
    linked_summary.symlink_to(secret_file)
    monkeypatch.setattr(drill, "TRUTH", linked_truth)
    monkeypatch.setattr(drill, "RUN2", linked_summary)
    leaked = drill.run_classic_mutation_score_drill(ops_dir=real)
    leaked_text = (real / "classic_mutation_score_drill.json").read_text(encoding="utf-8")
    assert leaked["gate_j_complete"] is False
    assert secret not in leaked_text
    assert secret_file.read_bytes() == original

    truth = real / "truth.json"
    truth.write_text(json.dumps({"bugs": {"this-install-bug": {}}}), encoding="utf-8")
    summary = real / "summary.json"
    summary.write_text(
        json.dumps({"buggy": {"bugs": {"caught": ["this-install-bug"]}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(drill, "TRUTH", truth)
    monkeypatch.setattr(drill, "RUN2", summary)
    saved = drill.run_classic_mutation_score_drill(ops_dir=real)
    written = (real / "classic_mutation_score_drill.json").read_text(encoding="utf-8")
    assert saved["gate_j_complete"] is False
    assert saved["ok"] is True
    assert "this-install-bug" in written
    assert secret not in written
    assert secret_file.read_bytes() == original


def test_classic_mutation_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-classic-mutation-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "J")["status"] != "done"
    assert snap["complete"] is False
