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


def verify_sources(*, graph: list[str], dom: list[str] | None = None, routes: list[str] | None = None,
                   sitemap: list[str] | None = None, requirements: list[str] | None = None,
                   blocked: list[str] | None = None) -> dict:
    """Compare the graph with the other inventories. Unknown is never a pass."""
    seen = set(graph)
    blocked_set = set(blocked or [])
    inventories = list(dict.fromkeys([*(dom or []), *(routes or []), *(sitemap or [])]))
    covered, missed, blocked_rows, unknown = [], [], [], []
    for url in inventories:
        if url in blocked_set:
            blocked_rows.append({"url": url, "reason": "blocked"})
        elif url in seen:
            covered.append(url)
        else:
            missed.append(url)
    for url in requirements or []:
        if url not in seen and url not in blocked_set and url not in missed:
            unknown.append(url)
    return {
        "complete": not missed and not unknown,
        "covered": covered,
        "missed": missed,
        "blocked": blocked_rows,
        "unknown": unknown,
    }
