"""QX-A02 next-page score. The crawler picks the next state on purpose.

A new template, a failed or uncertain state, a recent change, and a short
distance from a critical journey raise the score. Payment and checkout
addresses are left out. This does not change how many products a listing sample
keeps.
"""
from .swarm import is_payment_url


def score_candidate(candidate: dict) -> int:
    """Higher means this page should be opened sooner."""
    score = 0
    if candidate.get("new_template"):
        score += 50
    if candidate.get("failed") or candidate.get("uncertain"):
        score += 40
    if candidate.get("changed"):
        score += 30
    distance = int(candidate.get("journey_distance") or 0)
    score += max(0, 20 - max(0, distance))
    return score


def rank_candidates(candidates: list[dict]) -> list[dict]:
    """Order pages by score. Checkout and payment addresses are not returned."""
    ranked = []
    for candidate in candidates:
        url = str(candidate.get("url") or "")
        if is_payment_url(url):
            continue
        row = dict(candidate)
        row["score"] = score_candidate(candidate)
        ranked.append(row)
    ranked.sort(key=lambda row: (-int(row["score"]), str(row.get("url") or "")))
    return ranked
