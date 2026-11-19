"""A mutation score reads this install's fixtures. A link is left unread."""
import json

import backend.fixture_mutation_suite_drill as drill
from backend.blueprint_progress import progress


def test_a_mutation_score_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-mutation"
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

    evidence = drill.run_fixture_mutation_suite_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_j_complete"] is False
    assert secret not in str(evidence)
    assert secret_file.read_bytes() == original
    assert [path.name for path in other.iterdir()] == ["secret.json"]

    real = tmp_path / "real"
    real.mkdir()
    truth = real / "truth.json"
    truth.write_text(json.dumps({"bugs": {"this-install-bug": {}}}), encoding="utf-8")
    summary = real / "summary.json"
    summary.write_text(
        json.dumps({"buggy": {"bugs": {"caught": ["this-install-bug"]}}}),
        encoding="utf-8",
    )
    linked_truth = real / "linked-truth.json"
    linked_truth.symlink_to(secret_file)
    linked_summary = real / "linked-summary.json"
    linked_summary.symlink_to(secret_file)
    monkeypatch.setattr(drill, "SUITES", (
        {"id": "leaked", "truth": linked_truth, "summary": linked_summary},
        {"id": "ours", "truth": truth, "summary": summary},
    ))
    saved = drill.run_fixture_mutation_suite_drill(ops_dir=real)
    written = (real / "fixture_mutation_suite_drill.json").read_text(encoding="utf-8")
    assert saved["gate_j_complete"] is False
    assert "this-install-bug" in written
    assert secret not in written
    assert secret_file.read_bytes() == original


def test_mutation_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-mutation-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "J")["status"] != "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
