"""Coverage policy shared by Android planning, execution and reporting."""
from collections import Counter
from pathlib import Path

from .finalization import read_json


def dashboard(root: Path) -> dict:
    from .android_resume import records, snapshot
    cases = read_json(root / "test_cases.json", [])
    # Final results contain synthetic 'not executed' entries; only the worker
    # journal proves an actual attempt completed while a run is still active.
    results = {row["id"]: row for row in read_json(root / "results.json", [])}
    results.update({row["id"]: row for row in records(root / "android_results.jsonl") if row.get("id")})
    rows = []
    for case in cases:
        result = results.get(case["id"], {})
        status = "blocked" if case.get("blocked") else result.get("outcome", "pending")
        reason = result.get("error") or case.get("automation_note") or ""
        if status == "passed" and not result.get("checks"):
            status, reason = "inconclusive", "No meaningful assertion was recorded."
        if not reason:
            reason = "Assertions verified." if status == "passed" else "Awaiting execution." if status == "pending" else "See case evidence."
        rows.append({"id": case["id"], "title": case["title"], "status": status,
                     "reason": reason, "expected": case.get("expected", ""),
                     "checks": result.get("checks", 0), "functional": bool(case.get("auto_flow_id") or case.get("contract_id"))})
    summary = read_json(root / "summary.json", {})
    interaction = read_json(root / "android_interaction.json", {})
    return {"cases": rows, "counts": dict(Counter(row["status"] for row in rows)),
            "controls": (summary.get("controls") or {}).get("rows", []),
            "gaps": [row for row in interaction.get("coverage", []) if row.get("status") != "passed"],
            "unvisited": read_json(root / "android_discovery.json", {}).get("unvisited", []),
            "resume": snapshot(root) if cases else {"can_resume": False, "pending": [], "uncertain": [], "completed": 0},
            "scope": "All discovered scenarios is not exhaustive coverage of every possible state. Stop, time, discovery and action-policy guards still apply."}


def full_run(config: dict) -> bool:
    """Count cutoffs are optional; approval, time limits and Stop still apply."""
    return bool(config.get("test_all_discovered") and config.get("interaction_testing"))
