"""Independent review blocker freeze stays unsigned for Gate G."""
from backend.independent_review_blocker_freeze_drill import (
    run_independent_review_blocker_freeze_drill,
)


def test_independent_review_blocker_freeze_stays_partial(tmp_path, monkeypatch):
    import backend.remaining_blockers_drill as blockers

    monkeypatch.setattr(
        blockers,
        "run_remaining_blockers_drill",
        lambda ops_dir=None: {
            "ok": True,
            "complete": False,
            "open_count": 6,
            "blockers": [
                {
                    "id": "H-drills",
                    "gate": "H",
                    "label": "DR",
                    "status": "open",
                    "local_partial_present": ["a.json"],
                    "local_partial_missing": [],
                }
            ],
        },
    )
    evidence = run_independent_review_blocker_freeze_drill(ops_dir=tmp_path)
    assert evidence["gate_g_complete"] is False
    assert evidence["signed_off"] is False
    assert evidence["ok"] is True
    assert evidence["freeze_sha256"]
    assert (tmp_path / "independent_review_blocker_freeze_drill.json").is_file()
