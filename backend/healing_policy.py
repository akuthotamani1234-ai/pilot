"""Gate E healing policy: locator-only repairs; assertions stay untouched.

Wraps the self-healing safe-repair check so apply_run and tests can record
policy evidence without re-implementing AST rules.
"""
from __future__ import annotations


def review_repair(old_code: str, new_code: str, *, need_tests: bool = True) -> dict:
    """Whether a proposed script repair is allowed under Gate E rules."""
    from .agents.self_healing import _safe_repair

    problem = _safe_repair(old_code or "", new_code or "", need_tests=need_tests)
    return {
        "allowed": problem is None,
        "reason": problem or "",
        "policy": "locator_only",
        "rule": "may change how elements are found; never what is asserted",
    }


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
