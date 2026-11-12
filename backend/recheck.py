"""Re-check a bug after it was fixed (TestOptim: "re-check after fix"): run ONLY the test of the chosen findings of an
earlier run again, against the website as it is now -> fixed / still failing / inconclusive.

The run's own scripts, pages, approved hosts and login form are reused (runs/<run>/generated_tests, app_map.json,
crawl.json, login.json). The run's saved login was deleted when it ended, so a logged-in test signs in again with the
test account from .env (or the one the tester created) - the account is never taken from the run. Each re-check is
added to runs/<run>/recheck.json (newest last). Started from the chat's 'Re-check' button or with
`main.py --recheck <run> <test id> ...`.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

from .config import settings

RECHECKABLE = ("product_defect", "rule_violation", "suspect", "assertion_failure")  # (bugs + questions, not script
#                                                                                   problems: those need a new run)
SAFE_SETTINGS = ("allowed_hosts", "environment", "allow_actions", "test_payment", "confirm_writes", "page_timeout_ms",
                 "test_timeout_s", "unsafe_link_words", "llm_provider", "llm_model")


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def tests_of(run_dir: Path, failure_ids: list[int]) -> list[str]:
    """The test (nodeid) of each chosen finding that can be re-checked."""
    fs = {f.get("id"): f for f in _json(Path(run_dir) / "failures.json", [])}
    return list(dict.fromkeys(fs[i]["nodeid"] for i in failure_ids if i in fs and fs[i].get("nodeid")
                              and fs[i].get("category") in RECHECKABLE))


def verdict(r: dict | None) -> str:
    if not r:
        return "not run"
    return {"passed": "fixed", "failed": "still failing", "error": "still failing"}.get(r.get("outcome"), "inconclusive")


def recheck(run_dir: Path, nodeids: list[str]) -> dict:
    """Run these tests of the run again. Returns {nodeid: {verdict, outcome, error, screenshot, when}} + a note."""
    from .agents.discovery import restore_login
    from .agents.executor import _read, _relative, _run_pytest
    from .agents.failure_analysis import _short_error
    run_dir = Path(run_dir)
    saved = _json(run_dir / "run_args.json", {})
    for k, v in (saved.get("settings") or {}).items():  # (the run's own scope and limits - never a secret)
        if k in SAFE_SETTINGS and hasattr(settings, k):
            setattr(settings, k, v)
    roles = _json(run_dir / "roles.json", {})
    state = {"run_dir": str(run_dir), "url": saved.get("url", ""), "site_key": saved.get("site_key", ""),
             "run_id": run_dir.name, "app_map": _json(run_dir / "app_map.json", []),
             "crawl": _json(run_dir / "crawl.json", {}), "login": _json(run_dir / "login.json", {}),
             "roles": {"roles": roles} if roles else {}}
    test_dir = run_dir / "generated_tests"
    if not test_dir.is_dir() or not nodeids:
        return {"results": {}, "note": "This run has no test scripts to run again."}
    try:
        note = restore_login(state).replace("Resume: ", "") if state["login"].get("logged_in") else ""
        out = run_dir / "recheck.jsonl"
        _run_pytest(state, test_dir, out, run_dir / "recheck_screenshots", select=nodeids, traces=True, headless=True)
        fresh = {r["nodeid"]: r for r in _read(out)}
        _relative(list(fresh.values()), run_dir)
    finally:
        shutil.rmtree(run_dir / ".private", ignore_errors=True)  # (the new login is only needed while it runs)
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    results = {n: {"verdict": verdict(fresh.get(n)), "outcome": (fresh.get(n) or {}).get("outcome", "not run"),
                   "error": _short_error((fresh.get(n) or {}).get("error") or "")[:400],
                   "screenshot": (fresh.get(n) or {}).get("screenshot"), "when": when} for n in nodeids}
    history = _json(run_dir / "recheck.json", {})
    for n, r in results.items():
        history.setdefault(n, []).append(r)
    (run_dir / "recheck.json").write_text(json.dumps(history, indent=1), encoding="utf-8")
    return {"results": results, "note": note}
