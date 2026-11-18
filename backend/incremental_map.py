"""QX-A13 incremental discovery. The next run starts from the saved map.

Changed templates, failed states, and unknowns are reopened. Unchanged pages
are smoke-checked. A fresh run reopens every current page.
"""


def _reopen(page: dict, saved: dict[str, dict]) -> bool:
    old = saved.get(page.get("url") or "")
    if old is None:
        return True
    if page.get("changed"):
        return True
    if page.get("status") in {"failed", "unknown"}:
        return True
    return page.get("template") != old.get("template")


def plan_pages(saved: list[dict], current: list[dict], *, fresh: bool) -> dict:
    """Choose which saved pages to reopen and which to smoke-check."""
    if fresh:
        return {
            "reopen": [page.get("url") or "" for page in current],
            "smoke": [],
            "reason": "the operator asked for a fresh run",
        }
    known = {str(page.get("url") or ""): page for page in saved}
    reopen, smoke = [], []
    for page in current:
        url = str(page.get("url") or "")
        if _reopen(page, known):
            reopen.append(url)
        else:
            smoke.append(url)
    return {"reopen": reopen, "smoke": smoke, "reason": "unchanged pages are smoke-checked"}
