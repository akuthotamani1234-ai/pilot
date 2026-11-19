"""A DemoStore mutation score reads this install's result. A link is left unread."""
import json

import backend.mutation_score_drill as drill
from backend.blueprint_progress import progress


def test_a_demostore_mutation_score_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-demostore"
    other = tmp_path / "other"
    other.mkdir()
    secret_file = other / "secret.json"
    secret_file.write_text(json.dumps({
        "buggy": {"bugs": {"caught": [secret]}},
    }), encoding="utf-8")
    original = secret_file.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    evidence = drill.run_mutation_score_drill(ops_dir=linked)
    assert "link" in evidence["reason"]
    assert evidence["ok"] is False
    assert evidence["gate_j_complete"] is False
    assert secret not in str(evidence)
    assert secret_file.read_bytes() == original
    assert [path.name for path in other.iterdir()] == ["secret.json"]

    real = tmp_path / "real"
    real.mkdir()
    linked_summary = real / "linked-summary.json"
    linked_summary.symlink_to(secret_file)
    monkeypatch.setattr(drill, "RUN7", linked_summary)
    leaked = drill.run_mutation_score_drill(ops_dir=real)
    leaked_text = (real / "mutation_score_drill.json").read_text(encoding="utf-8")
    assert leaked["gate_j_complete"] is False
    assert secret not in leaked_text
    assert secret_file.read_bytes() == original

    summary = real / "summary.json"
    summary.write_text(json.dumps({
        "buggy": {"bugs": {"caught": [row["id"] for row in drill.PLANTED]}},
    }), encoding="utf-8")
    monkeypatch.setattr(drill, "RUN7", summary)
    saved = drill.run_mutation_score_drill(ops_dir=real)
    written = (real / "mutation_score_drill.json").read_text(encoding="utf-8")
    assert saved["ok"] is True
    assert saved["gate_j_complete"] is False
    assert "cart_total" in written
    assert secret not in written
    assert secret_file.read_bytes() == original


def test_demostore_mutation_link_stays_on_the_sidebar():
    snap = progress()
    row = next(item for item in snap["upcoming"] if item["id"] == "G-demostore-mutation-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "J")["status"] != "done"
    assert snap["complete"] is False
