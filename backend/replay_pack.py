"""QX-A08 replay. A defect package can be run again from the recorded steps.

A package needs the environment, build, browser or device, seed, starting
state, test data, actions, network evidence, screenshots, and the assertion
that failed. A short summary is not enough to replay.
"""
import json
from pathlib import Path

FIELDS = (
    "environment",
    "build",
    "browser",
    "seed",
    "starting_state",
    "test_data",
    "actions",
    "network",
    "screenshots",
    "assertion",
)


def missing_fields(package: dict) -> list[str]:
    """Names of the fields a replay still needs."""
    missing = []
    for field in FIELDS:
        value = package.get(field)
        if value is None or value == "" or value == [] or value == {}:
            missing.append(field)
    return missing


def make_package(**fields: object) -> dict:
    """Build a package. It is complete only when every required field is present."""
    package = {field: fields.get(field) for field in FIELDS}
    package["missing"] = missing_fields(package)
    package["complete"] = not package["missing"]
    return package


def replay(package: dict) -> dict:
    """Return the recorded steps, or the list of fields that still block replay."""
    missing = missing_fields(package)
    if missing:
        return {"ran": False, "missing": missing, "steps": []}
    return {"ran": True, "missing": [], "steps": list(package.get("actions") or []),
            "executed": False, "evidence_ready": True}


def saved_replays(run_dir: Path) -> list[dict]:
    """The replay decision stored for one run. An empty list means nothing was recorded."""
    try:
        payload = json.loads((run_dir / "qx_replay.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    packages = payload.get("packages") if isinstance(payload, dict) else None
    return [row for row in packages or [] if isinstance(row, dict)]


def replay_tests(run_dir: Path) -> list[str]:
    """Test names a complete package can run again. A crawl finding with no test is left out."""
    names = []
    for row in saved_replays(run_dir):
        played = row.get("replay") if isinstance(row.get("replay"), dict) else {}
        name = str(row.get("id") or "")
        if played.get("ran") and "::" in name:
            names.append(name)
    return list(dict.fromkeys(names))


def run_saved(run_dir: Path) -> dict:
    """Run the saved tests whose replay packages are complete."""
    from .recheck import recheck

    names = replay_tests(run_dir)
    if not names:
        return {"ran": False, "reason": "no complete package names a test", "results": {}}
    if not (Path(run_dir) / "generated_tests").is_dir():
        return {"ran": False, "reason": "this run has no test scripts", "results": {}}
    out = recheck(run_dir, names)
    results = out.get("results") or {}
    if not results:
        return {"ran": False, "reason": out.get("note") or "test runner returned no results", "results": {}}
    if not any(row.get("outcome") not in (None, "not run") for row in results.values() if isinstance(row, dict)):
        return {"ran": False, "reason": "no selected test actually executed", "results": results}
    return {"ran": True, "reason": "", "results": results}
