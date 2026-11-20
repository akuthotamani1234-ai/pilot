"""Phase 4: cleanup must confirm remote deletion, not only flip a local flag."""
from backend.data_lifecycle import Lifecycle


def test_cleanup_confirmed_requires_remote_proof():
    life = Lifecycle("run-cleanup", "test")
    life.prepare(1)

    def boom(record):
        return {"deleted": False, "reason": "api 500"}

    out = life.cleanup_confirmed(1, remote_delete=boom)
    assert out["complete"] is False
    assert out["failed"] and out["failed"][0]["reason"] == "api 500"
    assert len(life.for_worker(1)) == 3  # still present locally


def test_cleanup_confirmed_marks_cleaned_only_after_remote_success():
    life = Lifecycle("run-cleanup", "test")
    life.prepare(1)
    seen = []

    def ok(record):
        seen.append(record["tag"])
        return {"deleted": True, "proof": f"deleted:{record['tag']}"}

    out = life.cleanup_confirmed(1, remote_delete=ok)
    assert out["complete"] is True
    assert len(out["confirmed"]) == 3
    assert life.for_worker(1) == []
    assert all(row["cleanup_proof"].startswith("deleted:") for row in out["confirmed"])
    assert len(seen) == 3
