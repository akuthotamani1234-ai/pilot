"""Gate I: approvals enqueue → decide contract drill.

Offline SQLite queue only. Auth/hosting still open — gate_i_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .approvals import create, decide_approval, list_approvals, snapshot

_HEAL = json.dumps({
    "old_code": (
        'def test_x(page):\n'
        '    page.locator("#a").click()\n'
        '    assert page.locator("#ok").is_visible()\n'
    ),
    "new_code": (
        'def test_x(page):\n'
        '    page.locator("#b").click()\n'
        '    assert page.locator("#ok").is_visible()\n'
    ),
    "failure_class": "locator",
})

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "approvals_drill.json"


def _linked_drill() -> dict:
    return {
        "gate_i_complete": False,
        "ok": False,
        "drill": "approvals_enqueue_decide",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_approvals_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_drill()
    work = Path(ops_dir) / "approvals_work" if ops_dir else (
        ROOT / "artifacts" / "ops" / "approvals_work"
    )
    db = work / "approvals.sqlite"
    if folder_is_linked(work) or folder_is_linked(db):
        return _linked_drill()
    work.mkdir(parents=True, exist_ok=True)

    accept_row = create("heal", "locator #buy", detail=_HEAL, path=db)
    reject_row = create("sensitive", "delete account", path=db)
    pending_before = list_approvals(status="pending", path=db)
    accepted = decide_approval(accept_row["id"], "yes", path=db)
    rejected = decide_approval(reject_row["id"], "", path=db)
    pending_after = list_approvals(status="pending", path=db)
    snap = snapshot(path=db)

    evidence = {
        "gate_i_complete": False,
        "drill": "approvals_enqueue_decide",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pending_before": len(pending_before),
        "pending_after": len(pending_after),
        "accepted_status": accepted.get("status"),
        "rejected_status": rejected.get("status"),
        "snapshot": {
            "gate_i_approvals_ready": snap.get("gate_i_approvals_ready"),
            "gate_i_complete": snap.get("gate_i_complete"),
            "pending": snap.get("pending"),
        },
        "ok": (
            len(pending_before) >= 2
            and accepted.get("status") == "accepted"
            and rejected.get("status") == "rejected"
            and len(pending_after) == 0
            and snap.get("gate_i_complete") is False
            and snap.get("gate_i_approvals_ready") is True
        ),
        "reason": (
            "Approvals enqueue→accept/reject verified offline; "
            "live hosted SSO / dashboard auth still open"
        ),
    }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out = (Path(ops_dir) / "approvals_drill.json") if ops_dir else EVIDENCE
    if folder_is_linked(dest) or folder_is_linked(out):
        return _linked_drill()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out.name, json.dumps(evidence, indent=2)):
        return _linked_drill()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "approvals_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
