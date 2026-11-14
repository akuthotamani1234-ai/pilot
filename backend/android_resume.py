"""Continue unexecuted cases without replaying completed or uncertain mutations."""
import json
from pathlib import Path

from .android_runtime import read_only_case


def records(path: Path) -> list[dict]:
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a killed worker may leave a partial final line
            if isinstance(row, dict):
                rows.append(row)
    return rows


def plan(root: Path, cases: list[dict]) -> dict:
    completed = {row["id"]: row for row in records(root / "android_results.jsonl") if row.get("id")}
    started = {row.get("id") for row in records(root / "android_attempts.jsonl")}
    legacy = not (root / "android_attempts.jsonl").is_file() and bool(
        completed or (root / "execution.json").is_file())
    pending, uncertain = [], []
    for case in cases:
        cid = case["id"]
        if cid in completed or case.get("blocked"):
            continue
        if (cid in started or legacy) and not read_only_case(case):
            uncertain.append({"id": cid, "title": case["title"], "outcome": "blocked", "checks": 0,
                              "exception_type": "InterruptedMutation",
                              "error": "Interrupted action may have changed app/server data. Reconcile that data before a new run; automatic resume will not repeat it."})
        else:
            pending.append(case)
    return {"pending": pending, "completed": list(completed.values()), "uncertain": uncertain}


def snapshot(root: Path) -> dict:
    cases = json.loads((root / "test_cases.json").read_text(encoding="utf-8"))
    result = plan(root, cases)
    return {"pending": [{"id": c["id"], "title": c["title"]} for c in result["pending"]],
            "completed": len(result["completed"]), "uncertain": result["uncertain"],
            "can_resume": bool(result["pending"] and (root / "generated_tests/test_android_generated.py").is_file()
                               and (root / ".private/checkpoint.sqlite").is_file())}
