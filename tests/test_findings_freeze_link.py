"""A findings freeze hashes this install's notes. A link is left unread."""
import hashlib

from backend.blueprint_progress import progress
from backend.independent_review_findings_freeze_drill import (
    run_independent_review_findings_freeze_drill,
)


def _freeze():
    return {
        "ok": True,
        "signed_off": False,
        "freeze_sha256": "abc123",
        "freeze": {"open_count": 6},
    }


def test_a_findings_freeze_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    import backend.independent_review_findings_freeze_drill as mod

    secret = "tenant-b-only-findings-freeze"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "independent_review_findings_freeze_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_independent_review_findings_freeze_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_g_complete"] is False
    assert refused["signed_off"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    notes = other / "secret-findings.md"
    notes.write_text(secret, encoding="utf-8")
    alias = tmp_path / "linked-findings.md"
    alias.symlink_to(notes)
    monkeypatch.setattr(mod, "FINDINGS", alias)
    monkeypatch.setattr(
        "backend.independent_review_blocker_freeze_drill.run_independent_review_blocker_freeze_drill",
        lambda ops_dir=None: _freeze(),
    )
    real = tmp_path / "real"
    real.mkdir()
    skipped = run_independent_review_findings_freeze_drill(ops_dir=real)
    written = (real / "independent_review_findings_freeze_drill.json").read_text(encoding="utf-8")
    assert skipped["findings_present"] is False
    assert skipped["gate_g_complete"] is False
    assert secret not in written
    assert skipped["combined"]["findings_sha256"] != hashlib.sha256(secret.encode()).hexdigest()

    own = tmp_path / "own-findings.md"
    token = "this-install-finding"
    own.write_text(token, encoding="utf-8")
    monkeypatch.setattr(mod, "FINDINGS", own)
    saved = run_independent_review_findings_freeze_drill(ops_dir=real)
    saved_text = (real / "independent_review_findings_freeze_drill.json").read_text(encoding="utf-8")
    assert saved["findings_present"] is True
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert saved["combined"]["findings_sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in saved_text
    assert secret not in saved_text
    assert kept.read_bytes() == original


def test_findings_freeze_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-findings-freeze-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-findings-freeze-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
