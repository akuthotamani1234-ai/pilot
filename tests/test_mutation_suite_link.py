"""A mutation score reads this install's fixtures. A link is left unread."""
import json

import backend.fixture_mutation_suite_drill as drill
from backend.blueprint_progress import progress


def test_a_mutation_score_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    calls = {"n": 0}
    real_planted = drill._planted_ids

    def _planted_ids(path):
        calls["n"] += 1
        return real_planted(path)

    monkeypatch.setattr(drill, "_planted_ids", _planted_ids)

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
    assert calls["n"] == 0
    assert secret not in str(evidence)
    assert secret_file.read_bytes() == original
    assert [path.name for path in other.iterdir()] == ["secret.json"]

    folder = tmp_path / "real"
    folder.mkdir()
    planted = folder / "fixture_mutation_suite_drill.json"
    planted.symlink_to(secret_file)
    skipped = drill.run_fixture_mutation_suite_drill(ops_dir=folder)
    assert skipped["ok"] is False
    assert calls["n"] == 0
    assert secret not in str(skipped)
    assert secret_file.read_bytes() == original
    assert planted.is_symlink()
    planted.unlink()

    truth = folder / "truth.json"
    truth.write_text(json.dumps({"bugs": {"this-install-bug": {}}}), encoding="utf-8")
    summary = folder / "summary.json"
    summary.write_text(
        json.dumps({"buggy": {"bugs": {"caught": ["this-install-bug"]}}}),
        encoding="utf-8",
    )
    linked_truth = folder / "linked-truth.json"
    linked_truth.symlink_to(secret_file)
    linked_summary = folder / "linked-summary.json"
    linked_summary.symlink_to(secret_file)
    monkeypatch.setattr(drill, "SUITES", (
        {"id": "leaked", "truth": linked_truth, "summary": linked_summary},
        {"id": "ours", "truth": truth, "summary": summary},
    ))
    saved = drill.run_fixture_mutation_suite_drill(ops_dir=folder)
    written = (folder / "fixture_mutation_suite_drill.json").read_text(encoding="utf-8")
    assert calls["n"] == 2
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
