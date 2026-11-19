"""A blocker freeze records this install's inventory. A link is left untouched."""
from backend.blueprint_progress import progress
from backend.independent_review_blocker_freeze_drill import (
    run_independent_review_blocker_freeze_drill,
)


def _inventory(label: str):
    return {
        "ok": True,
        "complete": False,
        "open_count": 6,
        "blockers": [
            {
                "id": "H-drills",
                "gate": "H",
                "label": label,
                "status": "open",
                "local_partial_present": ["a.json"],
                "local_partial_missing": [],
            }
        ],
    }


def test_a_blocker_freeze_does_not_follow_a_link_into_another_folder(tmp_path, monkeypatch):
    secret = "tenant-b-only-blocker-freeze"
    other = tmp_path / "other"
    other.mkdir()
    kept = other / "independent_review_blocker_freeze_drill.json"
    kept.write_text(secret, encoding="utf-8")
    original = kept.read_bytes()
    linked = tmp_path / "ops"
    linked.symlink_to(other, target_is_directory=True)

    refused = run_independent_review_blocker_freeze_drill(ops_dir=linked)
    assert "link" in refused["reason"]
    assert refused["ok"] is False
    assert refused["gate_g_complete"] is False
    assert refused["signed_off"] is False
    assert secret not in str(refused)
    assert kept.read_bytes() == original
    assert [path.name for path in other.iterdir()] == [kept.name]

    real = tmp_path / "real"
    real.mkdir()
    alias = real / kept.name
    alias.symlink_to(kept)
    monkeypatch.setattr(
        "backend.remaining_blockers_drill.run_remaining_blockers_drill",
        lambda ops_dir=None: _inventory(secret),
    )
    skipped = run_independent_review_blocker_freeze_drill(ops_dir=real)
    assert "link" in skipped["reason"]
    assert skipped["ok"] is False
    assert secret not in str(skipped)
    assert kept.read_bytes() == original
    assert [path.name for path in real.iterdir()] == [alias.name]

    owned = tmp_path / "owned"
    owned.mkdir()
    token = "this-install-blocker"
    monkeypatch.setattr(
        "backend.remaining_blockers_drill.run_remaining_blockers_drill",
        lambda ops_dir=None: _inventory(token),
    )
    saved = run_independent_review_blocker_freeze_drill(ops_dir=owned)
    written = (owned / kept.name).read_text(encoding="utf-8")
    assert saved["gate_g_complete"] is False
    assert saved["signed_off"] is False
    assert saved["ok"] is True
    assert token in written
    assert secret not in written
    assert kept.read_bytes() == original


def test_blocker_freeze_link_stays_on_the_sidebar():
    snap = progress()
    ids = [item["id"] for item in snap["upcoming"]]
    assert ids.count("G-blocker-freeze-link") == 1
    row = next(item for item in snap["upcoming"] if item["id"] == "G-blocker-freeze-link")
    assert row["status"] == "done"
    assert next(gate for gate in snap["gates"] if gate["id"] == "G")["status"] != "done"
    assert snap["complete"] is False
