"""The Studio sidebar separates live-verified checks (with runs) from self-reported code progress, and reading
it never rewrites tracked evidence files."""
import hashlib
from pathlib import Path

from backend.blueprint_progress import live_verification, progress

ROOT = Path(__file__).resolve().parents[1]


def test_live_checks_come_from_the_evidence_file_with_runs():
    live = live_verification()
    assert live["checks"], "docs/live-verification.json lists proven checks"
    assert all(c.get("run") and c.get("label") for c in live["checks"])
    snap = progress()
    assert snap["counts"]["live_verified"] == len(live["checks"])
    assert "not proof" in snap["status_meaning"]


def test_reading_progress_does_not_rewrite_tracked_evidence():
    path = ROOT / "docs" / "ops-evidence" / "remaining_blockers.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    progress()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
