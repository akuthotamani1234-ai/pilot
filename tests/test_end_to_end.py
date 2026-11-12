"""The WHOLE pipeline (main.py) against the local DemoShop: URL -> login -> discovery -> test cases -> scripts ->
sandboxed execution -> failure analysis -> report, then a regression run of the same tests and the comparison.
No AI (rule-based), hidden browser, separate runs/ and baseline/ folders. Takes a few minutes:
    python -m pytest tests/test_end_to_end.py -q
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.demo_app import PASSWORD, USER, DemoApp

pytestmark = pytest.mark.slow  # (runs the whole tester: quick checks leave it out with -m "not slow")
ROOT = Path(__file__).resolve().parent.parent
VERDICTS = {"Ready", "Ready with Risks", "Not Ready", "Insufficient Evidence"}


def _run(app, tmp_path, *extra, user=USER, password=PASSWORD):
    env = os.environ.copy()
    env.update({"LLM_PROVIDER": "none", "HEADLESS": "true", "SLOW_MO_MS": "0", "TEST_WORKERS": "2",
                "RUNS_DIR": str(tmp_path / "runs"), "BASELINE_DIR": str(tmp_path / "baseline"),
                "WORKSPACE_DIR": str(tmp_path / "ws"), "TEST_USERNAME": user, "TEST_PASSWORD": password,
                "AUTO_REGISTER": "false", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    r = subprocess.run([sys.executable, "main.py", app.url, "--no-open", "--max-pages", "25", *extra], check=False, cwd=ROOT,
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1200)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert password not in r.stdout + r.stderr
    runs = sorted((tmp_path / "runs").iterdir(), key=lambda p: p.name)
    return runs[-1], r.stdout


def test_whole_pipeline_then_regression_run(tmp_path):
    app = DemoApp().start()
    try:
        run, out = _run(app, tmp_path)
        s = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        assert s["verdict"] in VERDICTS and s["gates"]
        assert s["login_outcome"] == "success" and s["authenticated_pages"] >= 3
        assert s["pages"] >= 8 and s["tests"] > 20
        assert {"routes", "components", "execution"} <= set(s["coverage"])
        # the planted problems are found ...
        failures = json.loads((run / "failures.json").read_text(encoding="utf-8"))
        assert any(f["source"] == "crawler" and f["page_url"].endswith("/missing") for f in failures)
        assert any("undefinedFunction" in (f.get("error") or "") for f in failures)
        # ... and the contact form's own error messages ("This field is required") are recognised (no false bug)
        assert not any("Empty form was accepted" in (f.get("error") or "") for f in failures), \
            [f["error"] for f in failures if "Empty form" in (f.get("error") or "")]
        assert "/delete-all" not in app.visited and "/logout" not in app.visited
        assert s["verdict"] == "Not Ready"  # a page that does not open (HTTP 404) is a release blocker
        # every test case is structured, has a result and evidence when it failed
        from backend.agents.test_design import validate_case
        cases = json.loads((run / "test_cases.json").read_text(encoding="utf-8"))
        assert all(validate_case(c) == [] for c in cases)
        assert all(c["execution_status"] != "Not run" for c in cases if c["automation_status"] != "Not automated")
        # nothing secret was left behind
        assert not (run / ".private").exists()
        for f in run.rglob("*"):
            if f.is_file():
                assert PASSWORD.encode() not in f.read_bytes(), f
        assert (run / "report.html").exists() and (run / "test_cases.xlsx").exists()

        # regression: the same scripts again, compared with the first run
        run2, out2 = _run(app, tmp_path, "--reuse-tests")
        assert "regression run" in out2.lower()
        cmp = json.loads((run2 / "comparison.json").read_text(encoding="utf-8"))
        assert cmp["previous_run"] == run.name and cmp["counts"]
        assert "new test case" not in cmp["counts"]  # the same test cases (same stable IDs) ran again
    finally:
        app.stop()


def test_web_ui_url_runs_through_report(tmp_path, monkeypatch):
    """The web submission path starts the same engine and exposes its final report."""
    from fastapi.testclient import TestClient

    from backend import server

    runs = tmp_path / "runs"
    monkeypatch.setattr(server, "RUNS", runs)
    monkeypatch.setattr(server, "AUDIT", tmp_path / "audit.jsonl")
    for key, value in {
        "LLM_PROVIDER": "none",
        "LLM_MODEL": "",
        "HEADLESS": "true",
        "SLOW_MO_MS": "0",
        "TEST_WORKERS": "1",
        "RUNS_DIR": str(runs),
        "BASELINE_DIR": str(tmp_path / "baseline"),
        "WORKSPACE_DIR": str(tmp_path / "workspace"),
        "TEST_USERNAME": "",
        "TEST_PASSWORD": "",
        "AUTO_REGISTER": "false",
    }.items():
        monkeypatch.setenv(key, value)

    app = DemoApp().start()
    job_id = None
    try:
        with TestClient(server.app, base_url="http://127.0.0.1:8000") as client:
            assert client.get("/").status_code == 200
            checked = client.get("/api/check", params={"source": app.url})
            assert checked.status_code == 200 and checked.json()["ok"], checked.text
            started = client.post("/api/runs", headers={"X-Agentic-QA": "1"}, json={
                "source": app.url, "authorized": True, "environment": "test", "max_pages": 10,
                "max_depth": 4, "show_browser": False, "llm_provider": "none",
            })
            assert started.status_code == 200, started.text
            job_id = started.json()["id"]

            deadline = time.monotonic() + 900
            status = started.json()
            while status["status"] == "running" and time.monotonic() < deadline:
                time.sleep(2)
                status = client.get(f"/api/runs/{job_id}").json()
            assert status["status"] == "done", (
                f"run status={status['status']}; " + "\n".join(status.get("lines", [])[-30:]))

            run = runs / status["run"]
            summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
            cases = json.loads((run / "test_cases.json").read_text(encoding="utf-8"))
            results = json.loads((run / "results.json").read_text(encoding="utf-8"))
            assert (run / "report.html").is_file() and (run / "generated_tests").is_dir()
            assert summary["pages"] >= 3 and cases and results
            report = client.get(f"/api/report/{status['run']}")
            assert report.status_code == 200
            assert report.json()["summary"]["verdict"] == summary["verdict"]
    finally:
        if job_id is not None:
            job = server.jobs.get(job_id)
            if job and job["status"] == "running":
                server._kill(job)
            server.jobs.pop(job_id, None)
        app.stop()


def test_deep_testing_behind_the_login_on_a_shop(tmp_path):
    """DemoStore: log in (two-step) -> every page behind the login explored, inspected and tested -> journeys
    (search -> product -> size -> cart; orders -> details) -> protected actions Blocked -> honest coverage."""
    from tests.demo_store import EMAIL, PASSWORD as STORE_PW, DemoStore
    store = DemoStore().start()
    try:
        run, out = _run(store, tmp_path, "--max-pages", "0", user=EMAIL, password=STORE_PW)
        s = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        assert s["login_outcome"] == "success" and s["authenticated_pages"] >= 12
        cov = s["coverage"]
        P = cov["pages"]
        assert P["discovered"] >= P["inspected"] >= P["tested"] >= P["verified"] >= 12, P
        assert P["needs_permission"] == 1 and P["sampled"] >= 3
        cases = json.loads((run / "test_cases.json").read_text(encoding="utf-8"))
        status = {c.get("journey") or c.get("feature_kind") or c["id"]: c["execution_status"] for c in cases}
        assert status["product"] == "Passed", [c["actual_result"] for c in cases if c.get("journey") == "product"]
        assert status["orders"] == "Passed"
        for kind in ("filter", "sort", "pagination", "wishlist", "search"):  # every one works, none fails
            got = [(c["execution_status"], c["actual_result"]) for c in cases if c.get("feature_kind") == kind]
            assert any(s == "Passed" for s, _ in got) and not any(s == "Failed" for s, _ in got), (kind, got)
        # (the public deals page: a visitor asked to sign in is "needs a test account" - not passed, not a bug)
        fav = [c for c in cases if c.get("feature_kind") == "wishlist" and c["execution_status"] == "Skipped"]
        assert all("needs a test account" in c["actual_result"] for c in fav), [c["actual_result"] for c in fav]
        assert any(c["execution_status"] == "Blocked" for c in cases)  # e.g. 'Buy now' - never clicked
        assert cov["features"]["tests"] >= 5 and cov["journeys"]
        for never in ("POST /order", "GET /buy", "GET /logout"):
            assert never not in store.visited, never
        assert "POST /cart/add" in store.visited  # the shopping journey really added the item (test account)
        for f in run.rglob("*"):
            if f.is_file():
                assert STORE_PW.encode() not in f.read_bytes(), f
    finally:
        store.stop()


def test_a_repaired_script_is_run_again_and_reported_with_its_real_result(tmp_path):
    """Self-healing: after a frontend update ('Notify me': #notify -> #notify-me, the same words) the scripts of the
    last run break. The script is repaired by finding the same button on the new page; the repaired test AND the
    other tests of the same file run again; the original failure and the old script are kept as evidence. This time
    DemoStore also has its planted bugs, so the repaired 'Notify me' test must fail on its REAL check (no message) -
    a repair is never allowed to force a pass."""
    from tests.demo_store import EMAIL, PASSWORD as STORE_PW, DemoStore
    store = DemoStore().start()
    try:  # the first run (every page, also /deals with 'Notify me'): its scripts are saved as the baseline
        _run(store, tmp_path, "--max-pages", "0", user=EMAIL, password=STORE_PW)
    finally:
        store.stop()
    # This regression specifically exercises locator healing. Learned tests normally fall back from a stale selector
    # to the control's unchanged text, which correctly avoids a repair; disable that fallback for this one saved case.
    saved_learned = list((tmp_path / "baseline").rglob("test_learned.py"))
    assert len(saved_learned) == 1, saved_learned
    code = saved_learned[0].read_text(encoding="utf-8")
    start = code.index("def test_learned_5(page, console_errors):")
    end = code.find("\n@pytest.mark.", start)
    if end < 0:
        end = len(code)
    case = code[start:end]
    assert case.count("'name': 'Notify me'") == 1, case
    saved_learned[0].write_text(code[:start] + case.replace("'name': 'Notify me'", "'name': ''", 1) + code[end:],
                                encoding="utf-8")
    updated = DemoStore(port=store.port, bugs=True, renamed=True).start()
    try:
        run, out = _run(updated, tmp_path, "--max-pages", "0", "--reuse-tests", user=EMAIL, password=STORE_PW)
    finally:
        updated.stop()
    log = json.loads((run / "healing_log.json").read_text(encoding="utf-8"))
    fix = next((h for h in log if "#notify-me" in (h.get("change") or "")), None)
    assert fix, [(h["test"], h["status"], h.get("change")) for h in log]
    assert fix["method"] == "selector-match" and fix["change"].startswith("#notify ")
    assert (run / fix["backup"]).exists()  # the script before the repair is kept
    assert fix["related"], "the other tests of the repaired file must run again too"
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    r = next(x for x in results if x["nodeid"] == fix["nodeid"])
    assert r["healed_round"] == fix["round"] and r["before_healing"]["outcome"] in ("failed", "error")
    assert r["outcome"] == "failed" and "message" in (r.get("error") or ""), r  # the planted dead button
    assert fix["status"] == "repaired" and fix["rerun"]["outcome"] == "failed"
    failures = json.loads((run / "failures.json").read_text(encoding="utf-8"))
    assert next(f["category"] for f in failures if f.get("nodeid") == fix["nodeid"]) != "test_defect"
    for h in log:  # nothing is called healed without a passing result of the test run again
        if h["status"] == "healed":
            assert next(x for x in results if x["nodeid"] == h["nodeid"])["outcome"] == "passed", h
