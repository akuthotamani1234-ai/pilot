"""Gate A surface coverage summary from a finished app_map.

Counts iframe/frame inventory, open shadow roots, closed/unsupported hosts,
and API/openapi seed hints. Missing surfaces stay unknown — never a pass.
"""
from __future__ import annotations


def summarize_surfaces(app_map: list[dict] | None = None, crawl: dict | None = None) -> dict:
    pages = app_map or []
    crawl = crawl or {}
    frames = {"testable": 0, "external": 0, "unreachable": 0, "pages_with_frames": 0, "listed_iframes": 0}
    shadow = {"open_roots_seen": 0, "pages_with_shadow": 0, "closed_unsupported": 0}
    for page in pages:
        page_frames = page.get("frames") if isinstance(page.get("frames"), list) else []
        listed = page.get("iframes") if isinstance(page.get("iframes"), list) else []
        if page_frames or listed:
            frames["pages_with_frames"] += 1
        frames["listed_iframes"] += len(listed)
        for fr in page_frames:
            status = str((fr or {}).get("status") or "").lower()
            if status == "testable":
                frames["testable"] += 1
            elif status == "external":
                frames["external"] += 1
            else:
                frames["unreachable"] += 1
        roots = page.get("shadowRoots")
        try:
            n_roots = int(roots or 0)
        except (TypeError, ValueError):
            n_roots = 0
        if n_roots > 0:
            shadow["pages_with_shadow"] += 1
            shadow["open_roots_seen"] += n_roots
        for item in page.get("unsupported") or []:
            reason = str((item or {}).get("reason") or item or "").lower()
            if "shadow" in reason or "closed" in reason:
                shadow["closed_unsupported"] += 1

    found_by = crawl.get("found_by") if isinstance(crawl.get("found_by"), dict) else {}
    api = {
        "network_seeded": sum(1 for how in found_by.values() if how == "network"),
        "openapi_or_scrape": sum(1 for how in found_by.values() if how in {"scrape", "openapi", "sitemap"}),
        "blocked_requests": len(crawl.get("blocked_requests") or []),
    }
    evidence = {
        "pages": len(pages),
        "frames": frames,
        "shadow": shadow,
        "api": api,
    }
    unknown = []
    if not pages:
        unknown.append("no pages inventoried")
    if frames["pages_with_frames"] == 0 and frames["listed_iframes"] == 0:
        unknown.append("iframe inventory empty on this run")
    if shadow["open_roots_seen"] == 0 and shadow["closed_unsupported"] == 0:
        unknown.append("shadow DOM signals empty on this run")
    if api["network_seeded"] == 0 and api["openapi_or_scrape"] == 0:
        unknown.append("no API/network/openapi seeds recorded")
    return {
        "gate_a_surfaces_complete": False,
        "unknown": unknown,
        "evidence": evidence,
        "note": "Surface counts are run-local. Empty does not prove the site lacks iframes/shadow/API.",
    }
