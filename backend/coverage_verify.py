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


def _path_key(value: str) -> str:
    """Normalize a path or URL to a comparable path key (/shop, /product/{id})."""
    text = (value or "").strip()
    if "://" in text:
        from urllib.parse import urlparse
        text = urlparse(text).path or "/"
    if not text.startswith("/"):
        text = "/" + text
    return text.rstrip("/") or "/"


def _path_matches(pattern: str, path: str) -> bool:
    """Match truth paths like /product/{id} against discovered /product/12."""
    import re
    pat = _path_key(pattern)
    got = _path_key(path)
    if "{id}" in pat or "{*}" in pat:
        rx = re.escape(pat).replace(r"\{id\}", r"[^/]+").replace(r"\{\*\}", r".+")
        return re.fullmatch(rx, got) is not None
    return pat == got


def verify_truth_pages(*, discovered: list[str], truth_pages: list[dict],
                       inaccessible: list[dict] | None = None) -> dict:
    """Independent Gate A check: compare discovered paths to an owned truth manifest.

    Missing in-scope pages are missed (not complete). Authorized inaccessible paths that were
    classified as permission-blocked are covered. Unknowns are never a pass.
    """
    covered, missed, blocked_rows, unknown = [], [], [], []
    blocked_paths = {_path_key(row.get("path", "")) for row in (inaccessible or [])}
    for page in truth_pages:
        path = page.get("path") or ""
        hit = next((d for d in discovered if _path_matches(path, d)), None)
        if hit:
            covered.append(path)
        elif _path_key(path) in blocked_paths or any(_path_matches(path, b) for b in blocked_paths):
            blocked_rows.append({"url": path, "reason": "inaccessible"})
        elif page.get("how"):
            unknown.append(path)  # optional/hard-to-reach: report unknown, not silent pass
        else:
            missed.append(path)
    return {
        "complete": not missed and not unknown,
        "covered": covered,
        "missed": missed,
        "blocked": blocked_rows,
        "unknown": unknown,
        "denominator": len(truth_pages),
        "coverage_ratio": (len(covered) / len(truth_pages)) if truth_pages else 0.0,
    }
