"""Gate E: level-3 repairs apply only with a single-use approval token.

An auth-class locator change is allowed once. The same token cannot be reused.
An assertion edit stays rejected. Infrastructure cannot be approved.
``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = (
    ROOT / "docs" / "ops-evidence" / "production_healing_approval_gate_drill.json"
)

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


def run_production_healing_approval_gate_drill(*, ops_dir: Path | None = None) -> dict:
    from .healing_policy import (
        issue_healing_approval,
        reset_healing_approvals,
        review_repair,
    )

    reset_healing_approvals()
    blocked = review_repair(_OLD, _GOOD, failure_class="auth_problem")
    issued = issue_healing_approval(_OLD, _GOOD, "auth_problem")
    applied = review_repair(
        _OLD, _GOOD, failure_class="auth_problem",
        approval_token=issued.get("token") or "",
    )
    reused = review_repair(
        _OLD, _GOOD, failure_class="auth_problem",
        approval_token=issued.get("token") or "",
    )
    weaken = issue_healing_approval(_OLD, _BAD, "auth_problem")
    assertion = review_repair(
        _OLD, _BAD, failure_class="auth_problem",
        approval_token=weaken.get("token") or "",
    )
    abort = issue_healing_approval(_OLD, _GOOD, "infrastructure")
    reset_healing_approvals()
    ok = (
        blocked.get("allowed") is False
        and issued.get("ok") is True
        and applied.get("allowed") is True
        and reused.get("allowed") is False
        and assertion.get("allowed") is False
        and abort.get("ok") is False
    )
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_approval_gate",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "human_approval_gate",
        "auth_without_token_blocked": blocked.get("allowed") is False,
        "auth_with_token_allowed": applied.get("allowed") is True,
        "token_reuse_blocked": reused.get("allowed") is False,
        "assertion_change_blocked": assertion.get("allowed") is False,
        "infrastructure_not_approvable": abort.get("ok") is False,
        "production_suite_executed": False,
        "ok": ok,
        "reason": (
            "Healing approval gate enforced "
            "(level-3 locator repair once, reuse and assertion edits refused, "
            "infrastructure not approvable); "
            "production / third-party healing suite still open"
            if ok else
            "Healing approval gate incomplete; production suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "production_healing_approval_gate_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = (
            ROOT / "artifacts" / "ops"
            / "production_healing_approval_gate_drill.json"
        )
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
