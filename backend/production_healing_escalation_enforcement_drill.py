"""Gate E: escalation ladder is enforced on the repair path (not a live suite).

Auth and infrastructure proposals are refused even when the diff is
locator-only. A timeout may still be reviewed as a locator repair.
``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = (
    ROOT / "docs" / "ops-evidence"
    / "production_healing_escalation_enforcement_drill.json"
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


def _linked_enforcement() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "production_healing_escalation_enforcement",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_production_healing_escalation_enforcement_drill(
    *, ops_dir: Path | None = None,
) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked
    from .healing_policy import review_repair

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "production_healing_escalation_enforcement_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_enforcement()

    auth = review_repair(_OLD, _GOOD, failure_class="auth_problem")
    infra = review_repair(_OLD, _GOOD, failure_class="infrastructure")
    retry = review_repair(_OLD, _GOOD, failure_class="timeout")
    locator = review_repair(_OLD, _GOOD, failure_class="locator")
    ok = (
        auth.get("allowed") is False
        and infra.get("allowed") is False
        and retry.get("allowed") is True
        and locator.get("allowed") is True
        and infra.get("escalation", {}).get("level") == 4
    )
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_escalation_enforcement",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "policy_enforcement",
        "auth_blocked": auth.get("allowed") is False,
        "infrastructure_blocked": infra.get("allowed") is False,
        "timeout_allowed": retry.get("allowed") is True,
        "locator_allowed": locator.get("allowed") is True,
        "production_suite_executed": False,
        "ok": ok,
        "reason": (
            "Healing escalation enforced on the repair path "
            "(auth/infrastructure refused, timeout and locator still reviewed); "
            "production / third-party healing suite still open"
            if ok else
            "Healing escalation enforcement incomplete; production suite still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_enforcement()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_enforcement()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
