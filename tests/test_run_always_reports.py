"""A run ALWAYS ends with a report (main.run_pipeline): an agent that crashes, a stop from the web UI (the STOP file),
Ctrl+C or the run time limit -> report.html + summary.json with "Insufficient Evidence" and the reason first, no new
baseline - and `--resume` goes on after the last finished stage. The agents are replaced by small fakes here (no
browser, no AI), except the test-run stop, which runs a real sandboxed pytest."""
import json
import threading
import time
from pathlib import Path

import pytest

from backend import runctl
from backend.config import settings

PAGE = {"url": "http://127.0.0.1:9/", "slug": "home", "status": 200, "title": "Home", "links": [], "buttons": [],
        "inputs": [], "forms": [], "page_type": "content", "features": {}}


@pytest.fixture
def run(tmp_path, monkeypatch):
    """A fresh run folder, its own runs/ + baseline/, and the cheap agents faked (setup, change detection)."""
    from backend import cost, graph as graph_mod
    monkeypatch.setattr(settings, "runs_dir", tmp_path / "runs")
    monkeypatch.setattr(settings, "baseline_dir", tmp_path / "baseline")
    monkeypatch.setattr(settings, "run_time_limit_min", 0)
    run_dir = tmp_path / "runs" / "site_1"
    run_dir.mkdir(parents=True)
    cost.set_run_dir(run_dir)
    monkeypatch.setattr(graph_mod, "setup_agent", lambda s: {})
    monkeypatch.setattr(graph_mod, "change_detection_agent", lambda s: {"changes": {"first_run": True}})
    runctl.reset()
    yield run_dir
    runctl.reset()


def _start(run_dir: Path) -> dict:
    return {"source": PAGE["url"], "url": PAGE["url"], "site_key": "site", "run_id": run_dir.name,
            "run_dir": str(run_dir), "log": [], "heal_round": 0}


def _discovery(calls: list, wait_for_stop: bool = False):
    def agent(state):
        calls.append(1)
        if wait_for_stop:  # a long crawl that respects a stop request (like the real crawl loop)
            t0 = time.time()
            while not runctl.stopping() and time.time() - t0 < 20:
                time.sleep(0.05)
        crawl = {"limit": 25, "visited": 1, "not_visited_count": 4 if wait_for_stop else 0,
                 "limit_reached": wait_for_stop, "stopped": runctl.reason() if runctl.stopping() else ""}
        return {"app_map": [dict(PAGE)], "crawl": crawl, "login": {}, "crawl_issues": [],
                "log": state.get("log", []) + ["Discovery: 1 page."]}
    return agent


def _summary(run_dir: Path) -> dict:
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


def test_a_crash_still_writes_the_report_and_keeps_the_baseline(run, monkeypatch):
    from backend import graph as graph_mod
    from main import run_pipeline

    def broken(state):
        raise RuntimeError("boom in test design")
    monkeypatch.setattr(graph_mod, "discovery_agent", _discovery([]))
    monkeypatch.setattr(graph_mod, "test_design_agent", broken)
    final = run_pipeline(_start(run), run, run.name)

    assert final["incomplete"] and final["stopped_at"] == "test_design"
    assert (run / "report.html").exists()
    s = _summary(run)
    assert s["verdict"] == "Insufficient Evidence" and s["incomplete"]
    assert "boom in test design" in s["reasons"][0] and "writing the test cases" in s["reasons"][0]
    assert s["gates"][0]["id"] == "run_complete" and s["gates"][0]["status"] == "missing"
    assert any(x["id"] == "error" for x in s["limits_hit"])
    assert "This run is incomplete" in (run / "report.html").read_text(encoding="utf-8")
    assert not (settings.baseline_dir / "site").exists()  # an unfinished run never becomes the baseline
    # it can go on later: the checkpoint is kept, with the stage to run again
    assert (run / "checkpoint.sqlite").exists()
    assert json.loads((run / "resume.json").read_text(encoding="utf-8"))["stage"] == "test_design"


def test_resume_goes_on_after_the_last_finished_stage(run, monkeypatch):
    from backend import graph as graph_mod
    from main import run_pipeline
    calls = []
    monkeypatch.setattr(graph_mod, "discovery_agent", _discovery(calls))
    monkeypatch.setattr(graph_mod, "test_design_agent", lambda s: (_ for _ in ()).throw(RuntimeError("crash")))
    run_pipeline(_start(run), run, run.name)
    assert _summary(run)["incomplete"]

    # fixed: the resumed run starts again at test design - the website is NOT explored a second time
    monkeypatch.setattr(graph_mod, "test_design_agent", lambda s: {"test_cases": [], "log": s["log"] + ["designed"]})
    monkeypatch.setattr(graph_mod, "script_generator_agent", lambda s: {"scripts": []})
    final = run_pipeline(None, run, run.name, resume=True)

    assert len(calls) == 1
    assert not final.get("incomplete") and final["report_path"]
    assert not _summary(run)["incomplete"]
    assert "designed" in final["log"] and "Discovery: 1 page." in final["log"]  # the state of the first part
    assert (settings.baseline_dir / "site" / "meta.json").exists()  # finished now: the baseline is saved
    assert not (run / "checkpoint.sqlite").exists() and not (run / "resume.json").exists()


def test_the_run_time_limit_stops_the_run_and_reports_what_was_done(run, monkeypatch):
    from backend import graph as graph_mod
    from main import run_pipeline
    monkeypatch.setattr(settings, "run_time_limit_min", 0.01)  # 0.6 s
    monkeypatch.setattr(graph_mod, "discovery_agent", _discovery([], wait_for_stop=True))
    t0 = time.time()
    final = run_pipeline(_start(run), run, run.name)

    assert time.time() - t0 < 15
    assert final["incomplete"] and final["stop_kind"] == "run_time_limit"
    s = _summary(run)
    assert s["verdict"] == "Insufficient Evidence" and "RUN_TIME_LIMIT_MIN" in s["reasons"][0]
    assert s["pages"] == 1  # the page found before the stop is in the report
    ids = {x["id"] for x in s["limits_hit"]}
    assert {"run_time_limit", "crawl_stopped"} <= ids
    assert json.loads((run / "resume.json").read_text(encoding="utf-8"))["stage"] == "discovery"  # cut short: again


def test_the_stop_button_gives_a_partial_report(run, monkeypatch):
    from backend import graph as graph_mod
    from main import run_pipeline
    monkeypatch.setattr(graph_mod, "discovery_agent", _discovery([], wait_for_stop=True))
    threading.Timer(0.8, lambda: (run / "STOP").write_text("stopped from the web UI", encoding="utf-8")).start()
    final = run_pipeline(_start(run), run, run.name)

    assert final["incomplete"] and final["stop_kind"] == "user_stop"
    s = _summary(run)
    assert "you stopped the test" in s["reasons"][0] and "exploring the website" in s["reasons"][0]
    assert any(x["id"] == "user_stop" for x in s["limits_hit"])


def test_an_unfinished_run_is_never_ready():
    from backend.agents.reporter import decide_verdict
    page = {"url": "https://x.test/", "slug": "home", "status": 200, "title": "Home"}
    state = {"app_map": [page], "log": [], "results": [{"nodeid": "a", "test": "test_a", "file": "test_site.py",
                                                        "outcome": "passed"}], "failures": [], "login": {},
             "crawl": {"limit_reached": False}, "healing_log": []}
    assert decide_verdict(state)[0] != "Insufficient Evidence"
    verdict, reasons, gates = decide_verdict(dict(state, incomplete=True, incomplete_reason="The run was stopped."))
    assert verdict == "Insufficient Evidence" and reasons[0] == "The run was stopped."
    assert gates[0]["id"] == "run_complete"


def test_every_limit_that_was_hit_is_listed(tmp_path):
    from backend.agents.reporter import limits_hit
    (tmp_path / "execution.json").write_text(json.dumps({"timed_out": True}), encoding="utf-8")
    state = {"crawl": {"limit_reached": True, "visited": 25, "limit": 25, "not_visited_count": 40,
                       "time_limit_reached": True, "time_limit_min": 30},
             "cases_left_out": 7, "results": [{"error_type": "TestTimeout", "error": ""}], "log": []}
    ids = [x["id"] for x in limits_hit(state, tmp_path)]
    assert ids == ["page_limit", "crawl_time_limit", "test_case_limit", "suite_timeout", "test_timeout"]
    assert limits_hit({"crawl": {}, "log": []}, tmp_path / "none") == []


def test_a_stop_ends_the_test_run_within_seconds_and_keeps_its_browsers_closed(tmp_path, monkeypatch):
    from backend.agents.executor import execution_agent
    from backend.agents.script_generator import TEMPLATES
    run_dir = tmp_path / "run"
    tests = run_dir / "generated_tests"
    tests.mkdir(parents=True)
    for name in ("conftest.py", "pytest.ini"):
        (tests / name).write_text((TEMPLATES / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tests / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(60)\n    assert True\n",
                                        encoding="utf-8")
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "test_workers", 1)
    monkeypatch.setattr(settings, "test_timeout_s", 120)
    runctl.reset()
    stopper = threading.Timer(4, runctl.request_stop, args=("user_stop", "you stopped the test"))
    stopper.start()
    try:
        t0 = time.time()
        out = execution_agent({"run_dir": str(run_dir), "url": "http://127.0.0.1:9/", "log": [],
                               "crawl": {"approved_hosts": ["127.0.0.1"]}})
        took = time.time() - t0
    finally:
        stopper.cancel()
        runctl.reset()
    assert took < 30, took
    assert json.loads((run_dir / "execution.json").read_text(encoding="utf-8"))["stopped"] is True
    assert "stopped early" in out["log"][-1]
