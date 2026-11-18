"""QX-A10 one journey across website, mobile web, and Android.

A difference is reported. It is a failure only when the approved spec says
the surfaces must match.
"""


def compare_journey(journey_id: str, steps_by_surface: dict[str, list[str]], *, must_match: bool) -> dict:
    """Compare the steps of one business journey on each surface."""
    surfaces = sorted(steps_by_surface)
    baseline = steps_by_surface[surfaces[0]] if surfaces else []
    differences = []
    for name in surfaces[1:]:
        steps = list(steps_by_surface[name])
        if steps != list(baseline):
            differences.append({"surface": name, "steps": steps})
    failed = bool(differences) and bool(must_match)
    if failed:
        status = "failed"
    elif differences:
        status = "reported"
    else:
        status = "matched"
    return {
        "journey_id": journey_id,
        "differences": differences,
        "failed": failed,
        "status": status,
    }
