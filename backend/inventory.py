"""The application's feature inventory, kept ACROSS runs: every page and feature any run found on an application, what
the latest run did with it, and which requirements its tests verified - so nothing found is silently forgotten.

inventory/<host>.json (one per application; written after each run's report, from runs/<run>/registry.json):
  features   id (the registry's stable id), level (control / feature / workflow), kind, name, pages, first / last
             seen, how many runs saw it, the latest status and why, the last run that tested / verified it, the
             requirement test cases whose tests exercised it (from the run's test_cases.json - evidence, not guessed),
             and a coverage class:
               verified        a test checked its result and passed
               failed          a test of it failed
               blocked         protected (it could pay / delete ...) or needs a test account / other permissions
               not tested      found, no test yet (with why)
               not reached     seen in an earlier run, not on the pages the latest run reached
  pages      the same for page patterns (discovered / inspected / needs permission / failed to open / not reached)
  summary    counts per class, and the discovery limits the latest run reported (sampling, budgets, logins) - the
             inventory never claims that everything was found
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = Path(os.environ.get("QPILOT_INVENTORY_DIR") or ROOT / "inventory")


def _file(host: str) -> Path:
    return FOLDER / (re.sub(r"[^A-Za-z0-9_.-]", "_", host or "app")[:120] + ".json")


def coverage_class(status: str) -> str:
    s = (status or "").lower()
    if s == "verified":
        return "verified"
    if s in ("failed", "flaky"):
        return "failed"
    if s in ("blocked", "needs_login", "needs login", "needs a test account", "needs_permission", "protected"):
        return "blocked"
    return "not tested"


def load(host: str) -> dict:
    from .finalization import folder_is_linked
    f = _file(host)
    if folder_is_linked(FOLDER) or not f.is_file() or f.is_symlink():
        return {"host": host, "features": {}, "pages": {}, "runs": []}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"host": host, "features": {}, "pages": {}, "runs": []}


def _requirements_by_test(run_dir: Path) -> dict[str, set[str]]:
    """test function name -> the requirement test cases (TC-...) whose test it is (the run's test_cases.json)."""
    out: dict[str, set[str]] = {}
    f = Path(run_dir) / "test_cases.json"
    try:
        cases = json.loads(f.read_text(encoding="utf-8")) if f.is_file() and not f.is_symlink() else []
    except (OSError, ValueError):
        cases = []
    for c in cases if isinstance(cases, list) else []:
        tc = c.get("requirement_test") if isinstance(c, dict) else None
        for t in (c.get("tests") or []) if tc else []:
            out.setdefault(str(t), set()).add(tc)
    return out


def _requirement_code(run_dir: Path) -> dict[str, str]:
    """requirement test case -> the code of its generated test function(s) (test_flows_ai.py)."""
    import ast
    by_test = _requirements_by_test(run_dir)
    f = Path(run_dir) / "generated_tests" / "test_flows_ai.py"
    out: dict[str, str] = {}
    try:
        tree = ast.parse(f.read_text(encoding="utf-8")) if f.is_file() and not f.is_symlink() else None
    except (OSError, SyntaxError, ValueError):
        tree = None
    for node in (tree.body if tree else []):
        if isinstance(node, ast.FunctionDef):
            for tc in by_test.get(node.name, set()):
                out[tc] = out.get(tc, "") + "\n" + ast.unparse(node)
    return out


def merge(host: str, run_dir: Path, reg: dict | None = None) -> dict:
    """Fold one finished run's registry into the application's inventory. Returns the inventory."""
    from . import registry as registry_mod
    from .finalization import folder_is_linked
    reg = reg or registry_mod.load(run_dir) or {}
    inv = load(host)
    run = Path(run_dir).name
    now = time.time()
    by_test = _requirements_by_test(run_dir)
    code = _requirement_code(run_dir)  # (a requirement test exercises a feature when its code uses that feature's
    seen_now = set()                   #  own selectors - evidence, not a guess from words)
    for f in (reg.get("features") or {}).values() if isinstance(reg.get("features"), dict) else reg.get("features", []):
        fid = f.get("id")
        if not fid:
            continue
        seen_now.add(fid)
        old = inv["features"].get(fid, {"first_seen": now, "runs_seen": 0, "requirements": [], "history": []})
        reqs = set(old.get("requirements") or [])
        for t in f.get("tests") or []:
            reqs |= by_test.get(str(t).split("::")[-1], set())
        selectors = [x for x in [f.get("selector"), *(f.get("uses") or [])] if isinstance(x, str) and len(x) > 3]
        reqs |= {tc for tc, src in code.items() if any(sel in src for sel in selectors)}
        status = str(f.get("status") or "")
        cls = coverage_class(status)
        entry = {**old, "id": fid, "level": f.get("level"), "kind": f.get("kind"), "name": f.get("name"),
                 "pages": sorted(set(old.get("pages") or []) | set(f.get("pages") or []))[:20],
                 "last_seen": now, "last_run": run, "runs_seen": int(old.get("runs_seen") or 0) + 1,
                 "status": status, "coverage": cls, "why": str(f.get("why") or "")[:300],
                 "requirements": sorted(reqs)[:50],
                 "history": ((old.get("history") or []) + [{"run": run, "status": status}])[-10:]}
        if cls in ("verified", "failed"):
            entry["last_tested_run"] = run
        if cls == "verified":
            entry["last_verified_run"] = run
        inv["features"][fid] = entry
    for fid, entry in inv["features"].items():
        if fid not in seen_now and entry.get("last_run") != run:
            entry["coverage"] = "not reached"
            entry["why"] = f"not on the pages the latest run ({run}) reached"
    for p in (reg.get("pages") or {}).values() if isinstance(reg.get("pages"), dict) else reg.get("pages", []):
        pid = p.get("id")
        if pid:
            inv["pages"][pid] = {**inv["pages"].get(pid, {"first_seen": now}), "id": pid,
                                 "pattern": p.get("pattern") or p.get("url"), "status": p.get("status"),
                                 "last_run": run, "last_seen": now}
    counts: dict[str, int] = {}
    for e in inv["features"].values():
        counts[e["coverage"]] = counts.get(e["coverage"], 0) + 1
    limits = (reg.get("counts") or {}).get("pages") or {}
    inv.update(host=host, updated=now, runs=((inv.get("runs") or []) + [run])[-50:],
               summary={"features": len(inv["features"]), "by_coverage": counts,
                        "with_requirements": sum(1 for e in inv["features"].values() if e.get("requirements")),
                        "pages": len(inv["pages"]),
                        "latest_run_limits": {k: v for k, v in limits.items()
                                              if k in ("sampled_out", "not_reached", "needs_permission",
                                                       "failed_to_open") and v},
                        "note": "Only what runs reached is listed: pages not reached, sampled pages and areas behind "
                                "other permissions are counted in latest_run_limits - this is not proof that every "
                                "feature of the application was found."})
    if not folder_is_linked(FOLDER):
        FOLDER.mkdir(exist_ok=True)
        f = _file(host)
        if not f.is_symlink():
            f.write_text(json.dumps(inv, indent=1, default=str), encoding="utf-8")
    return inv
