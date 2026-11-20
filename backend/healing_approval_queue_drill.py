"""Gate E: the approvals queue cannot override healing policy.

A person saying yes applies a heal only when the diff is allowed. The same
diff cannot be accepted twice. Assertion edits and infrastructure stay
rejected. ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "healing_approval_queue_drill.json"

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


def _linked_drill() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "healing_approval_queue",
        "production_suite_executed": False,
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_healing_approval_queue_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    out_name = "healing_approval_queue_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    work = Path(ops_dir) if ops_dir else (ROOT / "artifacts" / "ops")
    db = work / "healing_approval_queue.sqlite"
    if folder_is_linked(work) or folder_is_linked(db):
        return _linked_drill()
    from .approvals import create, decide_approval
    from .healing_policy import reset_healing_approvals

    work.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    reset_healing_approvals()
    prose = decide_approval(
        create("heal", "prose", detail="proposed css=#purchase", path=db)["id"],
        "yes",
        path=db,
    )
    weaken = decide_approval(
        create("heal", "assert", detail=_detail(_BAD, "auth_problem"), path=db)["id"],
        "yes",
        path=db,
    )
    infra = decide_approval(
        create("heal", "infra", detail=_detail(_GOOD, "infrastructure"), path=db)["id"],
        "yes",
        path=db,
    )
    first = decide_approval(
        create("heal", "auth", detail=_detail(_GOOD, "auth_problem"), path=db)["id"],
        "yes",
        path=db,
    )
    second = decide_approval(
        create("heal", "auth-again", detail=_detail(_GOOD, "auth_problem"), path=db)["id"],
        "yes",
        path=db,
    )
    reset_healing_approvals()
    ok = (
        prose.get("status") == "rejected"
        and weaken.get("status") == "rejected"
        and infra.get("status") == "rejected"
        and first.get("status") == "accepted"
        and second.get("status") == "rejected"
        and second.get("reason") == "healing approval already used"
    )
    evidence = {
        "gate_e_complete": False,
        "drill": "healing_approval_queue",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "approvals_queue_policy",
        "prose_rejected": prose.get("status") == "rejected",
        "assertion_rejected": weaken.get("status") == "rejected",
        "infrastructure_rejected": infra.get("status") == "rejected",
        "first_auth_accepted": first.get("status") == "accepted",
        "second_auth_rejected": second.get("status") == "rejected",
        "production_suite_executed": False,
        "ok": ok,
        "reason": (
            "Approvals queue enforces healing policy "
            "(yes cannot apply prose, assertion edits, or infrastructure; "
            "one auth locator repair applies once); "
            "production / third-party healing suite still open"
            if ok else
            "Healing approval queue enforcement incomplete; production suite still open"
        ),
    }
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, json.dumps(evidence, indent=2)):
        return _linked_drill()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "healing_approval_queue_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
