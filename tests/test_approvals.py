"""Gate I: durable approvals queue uses human_review.decide."""
import json
from pathlib import Path

import pytest

from backend.approvals import create, decide_approval, list_approvals, snapshot
from backend.healing_policy import reset_healing_approvals

_OLD = (
    'def test_x(page):\n'
    '    page.locator("#a").click()\n'
    '    assert page.locator("#ok").is_visible()\n'
)
_GOOD = (
    'def test_x(page):\n'
    '    page.locator("#b").click()\n'
    '    assert page.locator("#ok").is_visible()\n'
)
_BAD = (
    'def test_x(page):\n'
    '    page.locator("#a").click()\n'
    '    assert True\n'
)


def _detail(new_code: str, failure_class: str) -> str:
    return json.dumps({
        "old_code": _OLD,
        "new_code": new_code,
        "failure_class": failure_class,
    })


def test_create_list_and_decide(tmp_path: Path):
    db = tmp_path / "approvals.sqlite"
    row = create(
        "heal", "locator #buy", detail=_detail(_GOOD, "locator"), path=db,
    )
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


def test_heal_yes_cannot_bypass_policy(tmp_path: Path):
    db = tmp_path / "approvals.sqlite"
    reset_healing_approvals()
    prose = create("heal", "note", detail="proposed css=#purchase", path=db)
    weaken = create("heal", "assert", detail=_detail(_BAD, "auth_problem"), path=db)
    infra = create(
        "heal", "infra", detail=_detail(_GOOD, "infrastructure"), path=db,
    )
    auth = create("heal", "auth", detail=_detail(_GOOD, "auth_problem"), path=db)
    assert decide_approval(prose["id"], "yes", path=db)["status"] == "rejected"
    assert decide_approval(weaken["id"], "yes", path=db)["status"] == "rejected"
    assert decide_approval(infra["id"], "yes", path=db)["status"] == "rejected"
    accepted = decide_approval(auth["id"], "yes", path=db)
    reset_healing_approvals()
    assert accepted["status"] == "accepted"
    assert accepted["reason"] == "a person accepted it"


def test_an_accepted_heal_writes_the_script_once(tmp_path: Path):
    db = tmp_path / "approvals.sqlite"
    run = tmp_path / "run"
    script = run / "generated_tests" / "test_x.py"
    script.parent.mkdir(parents=True)
    script.write_text(_OLD, encoding="utf-8")
    reset_healing_approvals()
    detail = json.dumps({
        "old_code": _OLD, "new_code": _GOOD, "failure_class": "auth_problem",
        "run_dir": str(run), "file": "test_x.py",
    })
    row = create("heal", "locator", detail=detail, path=db)
    accepted = decide_approval(row["id"], "yes", path=db)
    assert accepted["status"] == "accepted"
    assert accepted["heal_applied"] is True
    assert script.read_text(encoding="utf-8") == _GOOD
    again = create("heal", "locator again", detail=detail, path=db)
    reused = decide_approval(again["id"], "yes", path=db)
    assert reused["status"] == "rejected"
    assert "already used" in reused["reason"]
    weaken = json.dumps({
        "old_code": _GOOD, "new_code": _BAD, "failure_class": "auth_problem",
        "run_dir": str(run), "file": "test_x.py",
    })
    script.write_text(_GOOD, encoding="utf-8")
    blocked = create("heal", "weaken", detail=weaken, path=db)
    assert decide_approval(blocked["id"], "yes", path=db)["status"] == "rejected"
    assert script.read_text(encoding="utf-8") == _GOOD
    escaped = json.dumps({
        "old_code": _OLD, "new_code": _GOOD, "failure_class": "locator",
        "run_dir": str(run), "file": "../outside.py",
    })
    outside = tmp_path / "outside.py"
    outside.write_text(_OLD, encoding="utf-8")
    escape = create("heal", "escape", detail=escaped, path=db)
    refused = decide_approval(escape["id"], "yes", path=db)
    assert refused["status"] == "rejected"
    assert outside.read_text(encoding="utf-8") == _OLD


def test_unknown_kind_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        create("ordinary", "x", path=tmp_path / "a.sqlite")
