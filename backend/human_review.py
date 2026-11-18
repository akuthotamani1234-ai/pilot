"""QX-A16 human review. Uncertain work waits for a person.

An uncertain assertion, a self-healing locator change, and a sensitive action
are not applied when nobody answers. The safe choice is to leave them unchanged.
"""
WAITING = frozenset({"uncertain_assertion", "heal", "sensitive"})
ACCEPTED = frozenset({"yes", "accept", "approved"})
REJECTED = frozenset({"no", "reject"})


def decide(kind: str, answer: str | None) -> dict:
    """Whether this change may be applied. No answer keeps the safe choice."""
    name = (kind or "").strip().lower()
    if name not in WAITING:
        return {"apply": True, "reason": "ordinary work does not wait"}
    choice = (answer or "").strip().lower()
    if choice in ACCEPTED:
        return {"apply": True, "reason": "a person accepted it"}
    if choice in REJECTED:
        return {"apply": False, "reason": "a person rejected it"}
    return {"apply": False, "reason": "no answer, so the safe choice stands"}


def proposal_fields(original_error: str) -> dict:
    """A locator repair stays a proposal, and the original failure is kept."""
    return {"proposal": True, "accepted": False, "original_error": original_error}


def withhold_unanswered(cases: list[dict], answers: dict | None = None) -> tuple[list[dict], int]:
    """Drop sensitive cases that a person has not accepted. Other cases stay."""
    answers = answers or {}
    kept = []
    held = 0
    for case in cases:
        if not case.get("approval_required"):
            kept.append(case)
            continue
        key = str(case.get("tc_id") or case.get("id") or "")
        answer = answers.get(key)
        text = answer.get("answer") if isinstance(answer, dict) else answer
        if decide("sensitive", text)["apply"]:
            kept.append(case)
        else:
            held += 1
    return kept, held
