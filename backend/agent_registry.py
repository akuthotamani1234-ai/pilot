"""Agent registry: every agent of a run, registered when the run starts, with its real state.

States come only from what the run actually does: waiting (registered, its turn has not come), running,
completed, failed, skipped (the run took another path). The file runs/<run>/agents.json is what the dashboard
shows; nothing here is simulated.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

# stage -> (agent name, role, what it waits for)
AGENTS = {
    "setup": ("Supervisor", "Validates the target, starts a project if needed, plans the run", []),
    "discovery": ("Website Discovery", "Explores pages, logs in, inventories controls, DOM/accessibility, API calls, "
                  "security headers and timings; explorer browsers read pages in parallel", ["setup"]),
    "change_detection": ("Change Detection", "Compares with the last run's baseline", ["discovery"]),
    "visual_check": ("Visual Testing", "Compares page looks with the approved baseline", ["discovery"]),
    "test_design": ("Test Design", "Turns discoveries and journeys into test cases", ["discovery"]),
    "review_gate": ("Human Review", "Lets you review cases before scripts are written", ["test_design"]),
    "script_generator": ("Script Generator", "Writes executable Playwright tests", ["test_design"]),
    "execution": ("Test Execution", "Runs the tests in parallel browser workers", ["script_generator"]),
    "failure_analysis": ("Failure Analysis", "Classifies failures: product, test, locator, infrastructure",
                         ["execution"]),
    "self_healing": ("Self-Healing", "Repairs locator drift only, then re-runs", ["failure_analysis"]),
    "report": ("Reporting", "Writes the evidence-backed report and verdict", ["failure_analysis"]),
    "save_baseline": ("Baseline", "Saves this run as the next comparison point", ["report"]),
    "integrations": ("Integrations", "Sends results to configured tools", ["report"]),
}
STATES = ("waiting", "running", "completed", "failed", "skipped")
_lock = threading.Lock()


def _path(run_dir) -> Path:
    return Path(run_dir) / "agents.json"


def _read(run_dir) -> dict:
    try:
        data = json.loads(_path(run_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(run_dir, data: dict) -> None:
    from .finalization import folder_is_linked
    path = _path(run_dir)
    if folder_is_linked(path.parent) or path.is_symlink():
        return
    tmp = path.with_name(f".agents.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def register(run_dir, stages: list[str]) -> dict:
    """Register every agent of this run as 'waiting'. Keeps states of a resumed run."""
    with _lock:
        data = _read(run_dir)
        known = {a["stage"]: a for a in data.get("agents", []) if isinstance(a, dict) and a.get("stage")}
        agents = []
        for stage in stages:
            name, job, deps = AGENTS.get(stage, (stage.replace("_", " ").title(), "", []))
            row = known.get(stage) or {"stage": stage, "name": name, "job": job, "status": "waiting",
                                       "depends_on": [d for d in deps if d in stages], "started": None,
                                       "finished": None, "detail": ""}
            agents.append(row)
        data = {"registered_at": data.get("registered_at") or time.time(), "agents": agents}
        _write(run_dir, data)
        return data


def update(run_dir, stage: str, status: str, detail: str = "") -> None:
    if status not in STATES:
        raise ValueError(status)
    with _lock:
        data = _read(run_dir)
        for row in data.get("agents", []):
            if row.get("stage") == stage:
                row["status"] = status
                now = time.time()
                if status == "running":
                    row["started"], row["finished"] = now, None
                elif status in ("completed", "failed"):
                    row["finished"] = now
                if detail:
                    row["detail"] = str(detail)[:300]
                break
        else:
            return
        _write(run_dir, data)


def finish(run_dir) -> None:
    """At the end of a run: agents whose turn never came were skipped (the run took another path or stopped)."""
    with _lock:
        data = _read(run_dir)
        changed = False
        for row in data.get("agents", []):
            if row.get("status") == "waiting":
                row["status"], changed = "skipped", True
            elif row.get("status") == "running":  # the process ended while it ran
                row["status"], row["detail"], changed = "failed", row.get("detail") or "the run ended while it ran", True
        if changed:
            _write(run_dir, data)


def snapshot(run_dir) -> dict:
    return _read(run_dir) or {"agents": []}


def detail_for(stage: str, out: dict) -> str:
    """One line of what an agent actually produced, from its own output."""
    if not isinstance(out, dict):
        return ""
    try:
        if stage == "discovery":
            pages = len(out.get("app_map") or [])
            auth = sum(1 for p in out.get("app_map") or [] if p.get("auth"))
            return f"{pages} page(s), {auth} behind the login"
        if stage == "test_design":
            return f"{len(out.get('test_cases') or [])} test case(s)"
        if stage == "script_generator":
            return f"{len(out.get('scripts') or out.get('test_files') or [])} test file(s)"
        if stage == "execution":
            results = out.get("results") or []
            from collections import Counter
            c = Counter(r.get("outcome") for r in results)
            return f"{len(results)} test(s): {c.get('passed', 0)} passed, {c.get('failed', 0)} failed"
        if stage == "failure_analysis":
            return f"{len(out.get('failures') or [])} finding(s)"
        if stage == "report":
            return f"verdict: {out.get('verdict') or (out.get('summary') or {}).get('verdict') or 'written'}"
    except Exception:
        return ""
    return ""
