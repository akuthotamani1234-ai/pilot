"""QX-A03 coverage check. The crawler does not grade its own completeness.

Every address on a listing must be chosen, left on purpose, or blocked.
Anything else is missed. Missed work means the listing is not complete.
"""


def verify_listing(urls: list[str], chosen: list[str], skipped: list[tuple[str, str]]) -> dict:
    """Compare a listing with the swarm's decision. Discovery does not pass this in for itself."""
    chosen_set = set(chosen)
    skipped_map = dict(skipped)
    covered, blocked, missed = [], [], []
    for url in urls:
        if url in chosen_set:
            covered.append(url)
        elif url in skipped_map:
            reason = skipped_map[url]
            if reason.startswith("checkout") or "never tested" in reason:
                blocked.append({"url": url, "reason": reason})
            else:
                covered.append(url)
        else:
            missed.append(url)
    return {
        "complete": not missed,
        "covered": covered,
        "missed": missed,
        "blocked": blocked,
        "unknown": [],
    }
