"""Live acceptance test on the public OrangeHRM demo (opt-in, never part of the offline suite).

    QPILOT_LIVE=1 QPILOT_LIVE_USER=Admin QPILOT_LIVE_PASSWORD=... python -m pytest -m live tests/test_live_orangehrm.py

Runs Qpilot from URL to report and checks the run's own evidence: login, ≥3 authenticated modules, learner and test
browsers working at the same time, executed assertions, screenshots, a trace per failed test, live events with
cursor positions, an API inventory, truthful agent states and no crashed worker. If the site cannot be reached the
test is reported as BLOCKED (skipped with that reason), never as passed. Nothing on the demo is changed: the run uses
the default test environment, where saving, deleting and other writes are never performed.
"""
import collections
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
URL = os.environ.get("QPILOT_LIVE_URL", "https://opensource-demo.orangehrmlive.com/")

pytestmark = [pytest.mark.live, pytest.mark.slow,
              pytest.mark.skipif(os.environ.get("QPILOT_LIVE") != "1", reason="live test: set QPILOT_LIVE=1")]


def _reachable(url: str) -> str:
    import requests
    try:
        r = requests.get(url, timeout=20)
        return "" if r.status_code < 500 else f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return str(e).split("(Caused by")[0][:200]


def _overlap(events: list[dict], prefix: str) -> int:
    """The largest number of workers with this prefix active in the same 5-second window."""
    mine = [e for e in events if str(e.get("worker", "")).startswith(prefix)]
    if not mine:
        return 0
    t0 = min(e["timestamp"] for e in mine)
    windows = collections.defaultdict(set)
    for e in mine:
        windows[int((e["timestamp"] - t0) // 5)].add(e["worker"])
    return max(len(w) for w in windows.values())


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    why = _reachable(URL)
    if why:
        pytest.skip(f"BLOCKED: {URL} is not reachable from here ({why})")
    user = os.environ.get("QPILOT_LIVE_USER", "")
    password = os.environ.get("QPILOT_LIVE_PASSWORD", "")
    if not (user and password):
        pytest.skip("BLOCKED: set QPILOT_LIVE_USER and QPILOT_LIVE_PASSWORD (the demo account) in the environment")
    before = set(glob.glob(str(ROOT / "runs" / "*")))
    env = dict(os.environ, TEST_USERNAME=user, TEST_PASSWORD=password, LLM_PROVIDER="none", HEADLESS="true",
               TEST_WORKERS=os.environ.get("QPILOT_LIVE_TEST_WORKERS", "4"),
               EXPLORE_WORKERS=os.environ.get("QPILOT_LIVE_EXPLORE_WORKERS", "6"), QA_LIVE_FRAMES="true",
               SWARM_SAMPLE="3", TEST_ENVIRONMENT="test")
    pages = os.environ.get("QPILOT_LIVE_PAGES", "8")
    proc = subprocess.run([sys.executable, "main.py", URL, "--max-pages", pages, "--no-open"], check=False, cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=3600)
    new = sorted(set(glob.glob(str(ROOT / "runs" / "*"))) - before, key=os.path.getmtime)
    assert new, f"no run folder was created\n{proc.stdout[-3000:]}\n{proc.stderr[-2000:]}"
    run = Path(new[-1])
    # (a run started from the command line prints its log; the web UI saves it as console.log)
    (run / "live_test_output.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    assert (run / "summary.json").is_file(), f"the run did not finish\n{proc.stdout[-3000:]}"
    return run


def test_login_succeeds_with_evidence(run_dir):
    login = json.loads((run_dir / "login.json").read_text(encoding="utf-8"))
    assert login["outcome"] == "success" and login["logged_in"], login
    assert len(login["evidence"]) >= 2


def test_at_least_three_authenticated_modules(run_dir):
    pages = json.loads((run_dir / "app_map.json").read_text(encoding="utf-8"))
    modules = {m.group(1) for p in pages if p.get("auth") for m in [re.search(r"index\.php/([a-z]+)/", p["url"])] if m}
    assert len(modules) >= 3, modules


def test_browsers_work_at_the_same_time(run_dir):
    events = [json.loads(line) for f in run_dir.glob("events.*.jsonl")
              for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert _overlap(events, "learner-") >= 2, "learner browsers never overlapped"
    assert _overlap(events, "gw") >= 2, "test workers never overlapped"
    assert any(e.get("point") for e in events), "no action recorded a cursor position"


def test_real_assertions_screenshots_and_traces(run_dir):
    results = [json.loads(line) for f in run_dir.glob("results.gw*.jsonl")
               for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert results and sum(r.get("checks", 0) for r in results) > 0
    assert list((run_dir / "screenshots").glob("*.png"))
    failed = [r for r in results if r["outcome"] == "failed"]
    traces = list((run_dir / "traces").glob("*.zip")) if (run_dir / "traces").is_dir() else []
    assert len(traces) == len(failed), (len(traces), len(failed))
    secret = os.environ.get("QPILOT_LIVE_PASSWORD", "")
    for zip_path in traces[:10]:
        import zipfile
        with zipfile.ZipFile(zip_path) as z:
            assert all(secret.encode() not in z.read(n) for n in z.namelist()), zip_path


def test_api_calls_were_inventoried(run_dir):
    inv = json.loads((run_dir / "api_inventory.json").read_text(encoding="utf-8"))
    assert inv["endpoints"] > 0


def test_agents_report_truthful_states(run_dir):
    agents = json.loads((run_dir / "agents.json").read_text(encoding="utf-8"))["agents"]
    states = {a["stage"]: a["status"] for a in agents}
    assert states["discovery"] == "completed" and states["execution"] == "completed" and states["report"] == "completed"
    assert "failed" not in states.values() and "running" not in states.values() and "waiting" not in states.values()


def test_no_worker_crashed(run_dir):
    console = (run_dir / "live_test_output.log").read_text(encoding="utf-8", errors="replace")
    assert "Exception in thread" not in console
    assert not (run_dir / "swarm_errors.json").exists()
