"""Gate E healing policy: locator-only repairs; assertions stay untouched.

Wraps the self-healing safe-repair check so apply_run and tests can record
policy evidence without re-implementing AST rules.
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

# Categories the failure classifier actually emits. Levels 3 and 4 never auto-apply.
_HUMAN = {
    "flaky", "auth_problem", "product_defect", "suspect",
    "rule_violation", "test_mistake",
}
_ABORT = {"infrastructure", "data_corruption", "security"}
_USED_APPROVALS: set[str] = set()
_ISSUED_APPROVALS: dict[str, str] = {}
_USED_DIGESTS: set[str] = set()
_USED_APPROVALS_MAX = 256
_RULE = "may change how elements are found; never what is asserted"


def reset_healing_approvals() -> None:
    """Clear process-local single-use healing approval tokens."""
    _USED_APPROVALS.clear()
    _ISSUED_APPROVALS.clear()
    _USED_DIGESTS.clear()


def repair_digest(old_code: str, new_code: str, failure_class: str) -> str:
    """Digest bound to one failure class and one exact script diff."""
    cat = (failure_class or "").strip().lower()
    raw = f"{cat}\n{old_code or ''}\n{new_code or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def healing_approval_used(token: str) -> bool:
    return (token or "").strip() in _USED_APPROVALS


def _note_approval_used(token: str) -> None:
    cleaned = (token or "").strip()
    if not cleaned:
        return
    _USED_APPROVALS.add(cleaned)
    while len(_USED_APPROVALS) > _USED_APPROVALS_MAX:
        _USED_APPROVALS.pop()


def issue_healing_approval(old_code: str, new_code: str, failure_class: str) -> dict:
    """Mint a single-use token for a level-3 repair. Abort classes cannot be approved."""
    decision = escalation_for(failure_class)
    if decision["level"] >= 4:
        return {
            "ok": False,
            "gate_e_complete": False,
            "reason": f"{decision['category']} cannot be approved",
            "escalation": decision,
        }
    if decision["auto_apply"]:
        return {
            "ok": False,
            "gate_e_complete": False,
            "reason": f"{decision['category']} does not need human approval",
            "escalation": decision,
        }
    digest = repair_digest(old_code, new_code, decision["category"])
    if digest in _USED_DIGESTS:
        return {
            "ok": False,
            "gate_e_complete": False,
            "reason": "healing approval already used",
            "escalation": decision,
        }
    token = uuid4().hex
    _ISSUED_APPROVALS[token] = digest
    while len(_ISSUED_APPROVALS) > _USED_APPROVALS_MAX:
        _ISSUED_APPROVALS.pop(next(iter(_ISSUED_APPROVALS)))
    return {
        "ok": True,
        "gate_e_complete": False,
        "token": token,
        "escalation": decision,
    }


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


def _decision(
    *,
    allowed: bool,
    reason: str,
    decision: dict | None = None,
) -> dict:
    out = {
        "allowed": allowed,
        "reason": reason,
        "policy": "locator_only",
        "rule": _RULE,
        "gate_e_complete": False,
    }
    if decision:
        out["escalation"] = decision
    return out


def review_repair(
    old_code: str,
    new_code: str,
    *,
    need_tests: bool = True,
    failure_class: str = "",
    approval_token: str = "",
    consume: bool = True,
) -> dict:
    """Whether a proposed script repair is allowed under Gate E rules.

    Level 3 applies only with a matching unused approval token, and still
    cannot change assertions. Level 4 cannot be approved. A preview passes
    ``consume=False`` so the token stays usable for the one write.
    """
    from .agents.self_healing import _safe_repair

    decision = escalation_for(failure_class) if (failure_class or "").strip() else None
    if decision and not decision["auto_apply"]:
        if decision["level"] >= 4:
            return _decision(
                allowed=False,
                reason=f"{decision['category']} requires {decision['action']}",
                decision=decision,
            )
        token = (approval_token or "").strip()
        digest = repair_digest(old_code, new_code, decision["category"])
        if healing_approval_used(token) or digest in _USED_DIGESTS:
            return _decision(
                allowed=False,
                reason="healing approval already used",
                decision=decision,
            )
        if _ISSUED_APPROVALS.get(token) != digest:
            return _decision(
                allowed=False,
                reason=f"{decision['category']} requires {decision['action']}",
                decision=decision,
            )
        problem = _safe_repair(old_code or "", new_code or "", need_tests=need_tests)
        if problem:
            return _decision(allowed=False, reason=problem, decision=decision)
        if consume:
            _note_approval_used(token)
            _USED_DIGESTS.add(digest)
            while len(_USED_DIGESTS) > _USED_APPROVALS_MAX:
                _USED_DIGESTS.pop()
        return _decision(allowed=True, reason="", decision=decision)
    problem = _safe_repair(old_code or "", new_code or "", need_tests=need_tests)
    return _decision(
        allowed=problem is None,
        reason=problem or "",
        decision=decision,
    )


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
