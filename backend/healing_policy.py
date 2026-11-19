"""Gate E healing policy: locator-only repairs; assertions stay untouched.

Wraps the self-healing safe-repair check so apply_run and tests can record
policy evidence without re-implementing AST rules.
"""
from __future__ import annotations

# Categories the failure classifier actually emits. Levels 3 and 4 never auto-apply.
_HUMAN = {
    "flaky", "auth_problem", "product_defect", "suspect",
    "rule_violation", "test_mistake",
}
_ABORT = {"infrastructure", "data_corruption", "security"}


def escalation_for(category: str) -> dict:
    """Map a failure category onto the healing escalation ladder.

    Locator-only review still applies at levels 1 and 2. Levels 3 and 4
    refuse automatic apply. ``gate_e_complete`` stays False.
    """
    cat = (category or "").strip().lower()
    if cat in _ABORT:
        level, action, auto = 4, "abort_and_page", False
    elif cat in _HUMAN:
        level, action, auto = 3, "human_approval_gate", False
    elif cat == "timeout":
        level, action, auto = 2, "auto_retry_with_budget", True
    else:
        level, action, auto = 1, "auto_locator_heal", True
    return {
        "category": cat,
        "level": level,
        "action": action,
        "auto_apply": auto,
        "gate_e_complete": False,
    }


def review_repair(
    old_code: str,
    new_code: str,
    *,
    need_tests: bool = True,
    failure_class: str = "",
) -> dict:
    """Whether a proposed script repair is allowed under Gate E rules."""
    from .agents.self_healing import _safe_repair

    decision = escalation_for(failure_class) if (failure_class or "").strip() else None
    if decision and not decision["auto_apply"]:
        return {
            "allowed": False,
            "reason": f"{decision['category']} requires {decision['action']}",
            "policy": "locator_only",
            "rule": "may change how elements are found; never what is asserted",
            "escalation": decision,
            "gate_e_complete": False,
        }
    problem = _safe_repair(old_code or "", new_code or "", need_tests=need_tests)
    out = {
        "allowed": problem is None,
        "reason": problem or "",
        "policy": "locator_only",
        "rule": "may change how elements are found; never what is asserted",
        "gate_e_complete": False,
    }
    if decision:
        out["escalation"] = decision
    return out


def summarize_healing(healing_log: list[dict] | None = None) -> dict:
    """Offline summary of healing attempts for Gate E evidence artifacts."""
    rows = healing_log or []
    methods = []
    rejected = 0
    applied = 0
    for entry in rows:
        method = str(entry.get("method") or "")
        if method:
            methods.append(method)
        status = str(entry.get("status") or "").lower()
        if status in {"rejected", "undone", "failed"} or entry.get("rejected"):
            rejected += 1
        if status in {"kept", "applied", "done"} or entry.get("kept"):
            applied += 1
        if entry.get("proposal") and not entry.get("accepted"):
            rejected += 1
    return {
        "gate_e_complete": False,
        "policy": "locator_only",
        "attempts": len(rows),
        "applied": applied,
        "rejected": rejected,
        "methods": methods[:40],
        "reason": "locator-only guards exist offline; live failure reproduction matrix still open",
    }
