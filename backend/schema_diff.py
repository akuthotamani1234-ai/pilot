"""QX-A15 API schema diff. A new spec is compared with the last accepted spec.

A workflow is broken when its method, path, or response fields no longer match.
Broken workflows are named before those tests are trusted.
"""


def _index(spec: dict) -> dict[tuple[str, str], dict]:
    found = {}
    for operation in spec.get("operations") or []:
        method = str(operation.get("method") or "").upper()
        path = str(operation.get("path") or "")
        if method and path:
            found[(method, path)] = operation
    return found


def diff_specs(previous: dict, current: dict) -> dict:
    """Name added, removed, and broken operations between two accepted specs."""
    old = _index(previous)
    new = _index(current)
    added = [f"{method} {path}" for method, path in sorted(set(new) - set(old))]
    removed = [f"{method} {path}" for method, path in sorted(set(old) - set(new))]
    broken = []
    for key in sorted(set(old) & set(new)):
        before = list(old[key].get("fields") or [])
        after = list(new[key].get("fields") or [])
        if before != after:
            broken.append({
                "operation": f"{key[0]} {key[1]}",
                "workflow": str(new[key].get("workflow") or old[key].get("workflow") or ""),
                "previous_fields": before,
                "current_fields": after,
            })
    return {"added": added, "removed": removed, "broken": broken, "trust_broken": bool(removed or broken)}
