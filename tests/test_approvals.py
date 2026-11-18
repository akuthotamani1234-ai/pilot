"""Gate I: durable approvals queue uses human_review.decide."""
from pathlib import Path

import pytest

from backend.approvals import create, decide_approval, list_approvals, snapshot


def test_create_list_and_decide(tmp_path: Path):
    db = tmp_path / "approvals.sqlite"
    row = create("heal", "locator #buy", detail="proposed css=#purchase", path=db)
    assert row["status"] == "pending"
    pending = list_approvals(status="pending", path=db)
    assert len(pending) == 1
    accepted = decide_approval(row["id"], "yes", path=db)
    assert accepted["status"] == "accepted"
    assert accepted["reason"] == "a person accepted it"
    assert list_approvals(status="pending", path=db) == []
    snap = snapshot(path=db)
    assert snap["gate_i_complete"] is False
    assert snap["gate_i_approvals_ready"] is True


def test_no_answer_keeps_safe_reject(tmp_path: Path):
    db = tmp_path / "approvals.sqlite"
    row = create("sensitive", "delete account", path=db)
    out = decide_approval(row["id"], "", path=db)
    assert out["status"] == "rejected"
    assert "safe" in out["reason"] or "no answer" in out["reason"]


def test_unknown_kind_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        create("ordinary", "x", path=tmp_path / "a.sqlite")
