"""QX-A17 trends. Repeated failures and flaky areas can change the next run's priority.

A trend does not rewrite the verdict of the run it was read from.
"""


def cluster_runs(runs: list[dict]) -> dict:
    """Count failures and flaky results by area across releases."""
    areas: dict[str, dict[str, int]] = {}
    for run in runs:
        for area in run.get("failures") or []:
            areas.setdefault(str(area), {"failures": 0, "flaky": 0})["failures"] += 1
        for area in run.get("flaky") or []:
            areas.setdefault(str(area), {"failures": 0, "flaky": 0})["flaky"] += 1
    priority = sorted(areas, key=lambda area: (-(areas[area]["failures"] + areas[area]["flaky"]), area))
    return {"areas": areas, "next_priority": priority}


def keep_verdict(verdict: str, _trends: dict) -> str:
    """The stored verdict of one run stays as it was."""
    return verdict
