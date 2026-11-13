"""Agent 4 — Test Execution Agent.

Runs the generated scripts with PyTest in a separate, limited process (the "sandbox"), collects results,
failure screenshots and traces, and optionally re-runs failed tests to spot flaky tests.
After Self-Healing it runs the repaired tests and the other tests of the repaired files again, and keeps or undoes
each repair from that evidence (_rerun_healed).

The sandbox (see also templates/conftest.py):
  * its own process - generated code never runs inside the web server or this pipeline
  * a clean environment: no API keys / GitHub token (only the test account, which the tests need)
  * Windows: a Job Object limits memory and the number of processes, and kills every browser it started when
    the run ends, times out or is stopped (other systems: its own process group, killed the same way)
  * a time limit per test and for the whole run
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .. import runctl
from ..actions import REFERENCE_NAV, SAFE_TEXT, TEST_ACCOUNT, WRITE, protected_pattern
from ..config import settings
from ..safety import AD_HOSTS, TRACKER_SAID, clean_env, is_private_host, redact
from ..state import QAState
from .discovery import fit_window_args

IS_WINDOWS = os.name == "nt"


def _worker_files(results_file: Path) -> list[Path]:
    """Results written by parallel workers: results.gw0.jsonl, results.gw1.jsonl, ..."""
    return sorted(results_file.parent.glob(f"{results_file.stem}.gw*{results_file.suffix}"))


def _result_count(results_file: Path) -> int:
    """How many pytest results have landed so far, without parsing the whole file."""
    total = 0
    for f in [results_file] + _worker_files(results_file):
        if f.exists():
            try:
                total += sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
            except OSError:
                pass
    return total


def _running_status(results_file: Path) -> str:
    try:
        data = json.loads((results_file.parent / f"running.{results_file.stem}.main.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not data:
        return "between tests"
    since = max(0, int(time.time() - float(data.get("since") or time.time())))
    test = f"{data.get('file', '?')}::{data.get('test', '?')}"
    steps = data.get("steps") or []
    tail = f" - last step: {steps[-1]['text']}" if steps else ""
    return f"{test} for {since}s{tail}"


# Watching in Chrome: ONE window shows the whole test run, one test after another - every test, also the small checks
# and the retries (Nov 3, 2026: 2 windows plus hidden small checks at the same time made the order impossible to
# follow). Slower than hidden browsers in parallel; a hidden run still uses TEST_WORKERS browsers.
WATCHED_WINDOWS = 1


def _watched_slow_mo_ms() -> int:
    """A visible run should be readable by default; hidden runs stay fast."""
    if settings.headless:
        return 0
    return max(0, min(settings.slow_mo_ms, 3000))


def _workers(n_tests: int | None, headless: bool | None = None) -> int:
    """How many browsers run tests at the same time: TEST_WORKERS hidden ones, or 1 window when you watch in Chrome."""
    if settings.test_workers <= 1:
        return 1
    try:
        import xdist  # noqa: F401  (pytest-xdist runs tests in parallel)
    except ImportError:
        return 1
    most = settings.test_workers if (settings.headless if headless is None else headless) else WATCHED_WINDOWS
    return max(1, min(most, settings.test_workers, n_tests or most))


def _stop_uncontained(proc: subprocess.Popen) -> None:
    """Stop a pytest process tree if Windows could not put it in the limiting Job Object."""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


class _Job:
    """Windows Job Object: memory + process-count limits, and everything in it dies when it is closed."""

    def __init__(self, memory_mb: int, max_processes: int):
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.k32 = k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = Extended()
        active_process, job_memory, kill_on_close = 0x8, 0x200, 0x2000
        info.BasicLimitInformation.LimitFlags = active_process | job_memory | kill_on_close
        info.BasicLimitInformation.ActiveProcessLimit = max_processes
        info.JobMemoryLimit = memory_mb * 1024 * 1024
        if not k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def add(self, proc: subprocess.Popen) -> None:
        if not self.k32.AssignProcessToJobObject(self.handle, int(proc._handle)):
            raise OSError("AssignProcessToJobObject failed")

    def kill(self) -> None:
        self.k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        self.k32.CloseHandle(self.handle)  # (kill-on-close: anything still running in the job ends now)


def _item_lists(app_map: list[dict]) -> dict:
    """{address pattern of item pages ('^/product/[^/]+/?$'): the page that lists them}. Demo shops rebuild their data
    every few minutes (new ids): a test can then open a CURRENT item from the list instead of a saved one that is gone."""
    import re

    from .discovery import _pattern
    out = {}
    for p in app_map:
        for l in (p.get("itemLinks") or {}).get("links") or []:
            pat = _pattern(l.get("href", ""), False)
            if pat and "{id}" in pat[1] and not pat[2]:
                rx = "^" + re.escape(pat[1]).replace(re.escape("{id}"), "[^/]+") + "/?$"
                out.setdefault(rx, p.get("final_url") or p["url"])
    return out


def _login_recipe(state: QAState) -> dict:
    """The login form the crawler signed in with: when the website ends the test account's session during the tests,
    they sign in again with it (conftest.py). Its boxes' addresses only - the password stays in TEST_PASSWORD."""
    from ..auth import login_form
    login = state.get("login") or {}
    entry = next((p for p in state.get("app_map") or [] if p.get("url") == login.get("page")), None)
    form = login_form(entry) if login.get("logged_in") and entry else None
    if not form or form.get("two_step"):
        return {}
    return {"page": login["page"], "at": entry.get("final_url") or "", "user": form["user"],
            "password": form["password"], "submit": form.get("submit") or ""}


def _env(run_dir: Path, test_dir: Path, results_file: Path, shot_dir: Path, state: QAState) -> dict:
    env = clean_env(os.environ.copy(), keep_test_account=True)  # no API keys / tokens for generated code
    for k in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID", "PYTEST_CURRENT_TEST"):
        env.pop(k, None)  # (the tester itself may run inside pytest: these belong to that run, not to the website's tests)
    crawl = state.get("crawl") or {}
    hosts = crawl.get("approved_hosts") or [urlparse(state.get("url", "")).hostname or ""]
    hosts = [h for h in dict.fromkeys(list(hosts) + settings.allowed_hosts) if h]
    env.update({
        "QA_RESULTS_FILE": str(results_file.resolve()),
        "QA_SCREENSHOT_DIR": str(shot_dir.resolve()),
        "QA_TRACE_DIR": str((run_dir / "traces").resolve()),
        "QA_RUN_DIR": str(run_dir.resolve()),
        "QA_BASE_URL": state.get("url", "") if str(state.get("url", "")).startswith("http") else "",
        "QA_ALLOWED_HOSTS": ",".join(hosts),
        "QA_AD_RX": AD_HOSTS.pattern,  # (ads / trackers: stopped silently in the tests too - pages load faster)
        "QA_TRACKER_SAID_RX": TRACKER_SAID.pattern,  # (... so the website's complaint about one is ours, not its error)
        "QA_TARGET_LOCAL": "1" if any(is_private_host(h, resolve=True) for h in hosts[:1]) else "0",
        "QA_TEST_TIMEOUT_S": str(settings.test_timeout_s),
        "QA_NAV_TIMEOUT_MS": str(max(settings.page_timeout_ms, 30000)),
        "HEADLESS": "true" if settings.headless else "false",
        "QA_WINDOW_ARGS": json.dumps(fit_window_args()),  # (watching: the whole window fits the screen)
        # watching in Chrome: default to a readable pace; hidden runs keep the browser at full speed
        "SLOW_MO_MS": str(_watched_slow_mo_ms()),
        # what test code may never click in THIS environment (enforced in conftest.py; production: every
        # consequential action; test / staging: what ALLOW_ACTIONS does not allow)
        "QA_PROTECTED_RX": protected_pattern(), "QA_TEST_ACCOUNT_RX": TEST_ACCOUNT.pattern,
        "QA_ENVIRONMENT": settings.environment, "QA_RUN_ID": run_dir.name,
        "QA_SAFE_TEXT_RX": SAFE_TEXT.pattern, "QA_WRITE_RX": WRITE.pattern,
        "QA_REFERENCE_NAV_RX": REFERENCE_NAV.pattern,
        # a link that says where it goes is protected only by an address that changes data (the crawler's rule)
        "QA_UNSAFE_LINK_RX": "|".join(re.escape(w) for w in settings.unsafe_link_words),
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
    })
    if settings.record_video:
        env["QA_VIDEO_DIR"] = str((run_dir / "videos").resolve())
    env["QA_ITEM_LISTS"] = json.dumps(_item_lists(state.get("app_map") or []))
    auth = run_dir / ".private" / "auth.json"  # the crawler logged in with the test account -> tests start logged in
    env["QA_AUTH_STATE"] = str(auth.resolve()) if auth.exists() else ""
    env["QA_LOGIN_FORM"] = json.dumps(_login_recipe(state) if auth.exists() else {})
    from .. import jscov  # (how much of the website's JavaScript the tests run: staging / a site on this PC)
    env["QA_JS_COVERAGE"] = "1" if jscov.enabled(env.get("QA_TARGET_LOCAL") == "1") else "0"
    # several user roles: each role's own saved login (its tests start in it - its password is never passed on)
    roles = ((state.get("roles") or {}).get("roles") or {})
    env["QA_ROLE_STATES"] = json.dumps({r: str((run_dir / ".private" / v["state"]).resolve()) for r, v in roles.items()
                                        if v.get("state") and (run_dir / ".private" / v["state"]).exists()})
    return env


def _run_pytest(state: QAState, test_dir: Path, results_file: Path, shot_dir: Path,
                select: list[str] | None = None, traces: bool = False, headless: bool | None = None) -> dict:
    """Run pytest in the sandbox. Returns {"timed_out", "stopped", "returncode", "sandbox"}.
    traces=True records a Playwright trace of every failing test (used for the retry of failed tests only:
    recording traces for every test makes a long run much slower). headless=True: hidden browsers, also while
    you watch the other tests in Chrome."""
    sandbox = "own process, clean environment, network + file guard, per-test time limit"
    # Cap the suite by suite_timeout AND by remaining run wall-clock minus analysis/report reserve.
    # Measure phase durations before raising ANALYSIS_RESERVE_S / REPORT_RESERVE_S / SUITE_TIMEOUT_S.
    suite_s = settings.suite_timeout_s
    rem = runctl.remaining_s()
    if rem is not None:
        leave = runctl.reserve_budget_s()
        suite_s = max(30, min(suite_s, int(rem - leave))) if rem > leave else 0
    if suite_s <= 0 or runctl.should_stop_heavy_work():
        print("  [execution] run time reserve reached before suite start - skipping new tests so analysis/report "
              "can finish", flush=True)
        return {"timed_out": True, "stopped": False, "returncode": -1, "sandbox": sandbox,
                "reserve_skip": True}
    for f in [results_file] + _worker_files(results_file):
        if f.exists():
            f.unlink()
    run_dir = test_dir.parent
    env = _env(run_dir, test_dir, results_file, shot_dir, state)
    env["QA_TRACES"] = "true" if traces else "false"
    if headless:
        env["HEADLESS"], env["SLOW_MO_MS"] = "true", "0"
    junit = results_file.with_name(results_file.stem + "_junit.xml")  # machine-readable results (CI tools)
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", "--continue-on-collection-errors",
           "--rootdir", str(test_dir.resolve()), f"--junitxml={junit.resolve()}"]
    if (test_dir / "pytest.ini").exists():
        cmd += ["-c", str((test_dir / "pytest.ini").resolve())]
    if state.get("resuming") and select is None:
        cmd += ["--deselect=" + node for node in state.get("resume_completed", [])]
    workers = _workers(len(select) if select else None, headless)
    if headless and not settings.headless:  # (the Chrome windows you are watching are browsers too)
        workers = max(1, workers - WATCHED_WINDOWS)
    if workers > 1:  # (the tests that change the cart - one 'cart' group - run one after another, in one browser)
        cmd += ["-n", str(workers), "--dist", "loadgroup"]
        print(f"  [execution] running tests in {workers} browsers at the same time")
    cmd += select or [str(test_dir.resolve())]

    # getattr: Linux unit tests force IS_WINDOWS to exercise Job Object fail-closed without the Win32 flag.
    kwargs = (
        {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        if IS_WINDOWS
        else {"start_new_session": True}
    )
    proc = subprocess.Popen(cmd, cwd=test_dir.resolve(), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", **kwargs)
    job = None
    if IS_WINDOWS:
        try:
            job = _Job(settings.sandbox_memory_mb, settings.sandbox_max_processes)
            job.add(proc)
            sandbox += f", max {settings.sandbox_memory_mb} MB / {settings.sandbox_max_processes} processes"
        except Exception as e:
            if job:
                try:
                    job.close()
                except OSError:
                    pass
                job = None
            _stop_uncontained(proc)
            raise RuntimeError("Windows Job Object limits could not be established; generated tests were stopped") from e
    timed_out = stopped = False
    deadline = time.time() + suite_s
    last_heartbeat = 0.0
    try:
        while True:
            try:  # short slices: a stop request (runctl) is seen within seconds - no output is lost between them
                out, _ = proc.communicate(timeout=2)
                break
            except subprocess.TimeoutExpired:
                if time.time() - last_heartbeat >= 30:
                    last_heartbeat = time.time()
                    print(f"  [execution] still running: {_result_count(results_file)} result(s) so far; "
                          f"{_running_status(results_file)}", flush=True)
                if time.time() < deadline and not runctl.should_stop_heavy_work():
                    continue
            stopped = runctl.stopping()
            timed_out = not stopped
            why = (runctl.reason() if stopped else
                   "run time reserve (ANALYSIS_RESERVE_S / REPORT_RESERVE_S)" if runctl.should_stop_heavy_work()
                   else f"the tests took longer than {settings.suite_timeout_s} s")
            print(f"  [execution] {why} - stopped them (the results so far are kept)")
            if job:
                job.kill()
            elif IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            out, _ = proc.communicate()
            break
    finally:
        if job:
            job.close()  # every browser the tests started ends with it
    log = results_file.with_name(results_file.stem + "_pytest_output.txt")  # pytest's own output, kept as evidence
    log.write_text(redact(out or ""), encoding="utf-8")
    return {"timed_out": timed_out, "stopped": stopped, "returncode": proc.returncode, "sandbox": sandbox}


def _read(results_file: Path) -> list[dict]:
    out = []
    for f in [results_file] + _worker_files(results_file):
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    print(f"  [execution] incomplete result line retained for investigation in {f.name}")
    return out


def _relative(results: list[dict], run_dir: Path) -> None:
    for r in results:  # screenshot / trace paths relative to the run folder, for the HTML report
        for key in ("screenshot", "trace"):
            if r.get(key):
                try:
                    r[key] = str(Path(r[key]).resolve().relative_to(run_dir.resolve())).replace("\\", "/")
                except ValueError:
                    pass


REAL_CHECK = ("product_defect", "assertion_failure", "auth_problem", "test_data")  # the script reached a real check


def _repair_verdict(result: dict | None, broke: list[str]) -> tuple[str, str]:
    """Keep or undo a repaired script, from the evidence of running it again:
      healed    the test passes now
      repaired  the script works now and the test fails on a REAL check - reported as it is, never forced to pass
      reverted  it did not run again, it is still a script problem, or other tests of the same file broke"""
    from .failure_analysis import classify
    if broke:
        return "reverted", (f"the repair broke {len(broke)} other test(s) that passed before: "
                            + ", ".join(b.split("::")[-1] for b in broke[:5]))
    if result is None:
        return "reverted", "the repaired test did not run again"
    if result["outcome"] == "passed":
        return "healed", ""
    if result["outcome"] == "skipped":
        return "repaired", f"the script works now; the test was skipped: {(result.get('error') or '')[:160]}"
    cat = classify(result)[0] if result["outcome"] in ("failed", "error") else "inconclusive"
    if cat in REAL_CHECK:
        return "repaired", f"the script works now; the test fails on a real check ({cat})"
    return "reverted", f"the repaired script still fails ({cat}) - the repair did not help"


def _related(results: list[dict], file: str, test_dir: Path) -> list[str]:
    """The tests that use a repaired file: every test of a repaired test file, and the tests (test_checks.py, an
    older run's test_flows.py) that call a repaired steps module."""
    callers = set()
    if file.startswith("steps_"):
        for f in test_dir.glob("test_*.py"):
            current = None
            for line in f.read_text(encoding="utf-8").splitlines():
                m = re.match(r"def (test_\w+)\(", line)
                current = m.group(1) if m else current
                if current and f"{file[:-3]}.step_" in line:
                    callers.add((f.name, current))
    return [r["nodeid"] for r in results if r["file"] == file or (r["file"], r["test"].split("[")[0]) in callers]


def _undo(test_dir: Path, run_dir: Path, file: str, entries: list[dict]) -> None:
    """Take back the repairs of one file that are not kept: a swapped selector is swapped back; when the whole file
    must go back (an AI rewrite, or another test broke) it is restored from the copy made before the round."""
    path = test_dir / file
    kept = [h for h in entries if h["status"] in ("healed", "repaired")]
    undo = [h for h in entries if h["status"] == "reverted"]
    whole = any(h["method"] == "llm" or not h.get("to") or "broke" in (h.get("why") or "") for h in undo) or not kept
    if whole:
        backup = run_dir / (undo[0].get("backup") or "")
        if undo[0].get("backup") and backup.exists():
            shutil.copy(backup, path)
        for h in kept:  # (their test ran with the file that is now taken back)
            h["status"], h["why"] = "reverted", "undone together with the other repairs of this file"
        return
    code = path.read_text(encoding="utf-8")
    keep_swaps = {(h["from"], h["to"]) for h in kept}
    for h in undo:
        if (h["from"], h["to"]) in keep_swaps:  # the same swap made another test work: it stays for that one
            h["status"], h["why"] = "still failing", (h.get("why") or "") + " (the change stays: it repaired another test)"
        else:
            code = code.replace(repr(h["to"]), repr(h["from"])).replace(json.dumps(h["to"]), json.dumps(h["from"]))
    path.write_text(code, encoding="utf-8")


def _merge_retry(results: list[dict], rerun: dict) -> None:
    """A retry's outcome, added to the first results. Passed on the retry => flaky (the first failure is kept).
    Failed again for ANOTHER reason (the first try's login was refused; the retry got further and met the real
    problem): the retry's failure is reported - its trace shows it - and the first one is kept as 'first_error'."""
    from .failure_analysis import _short_error
    for r in results:
        again = rerun.get(r["nodeid"])
        if again is None:
            continue
        r["rerun_outcome"] = again["outcome"]
        if again["outcome"] in ("failed", "error") and _short_error(again.get("error")) != _short_error(r.get("error")):
            r["first_error"] = r.get("error")
            r.update({k: again[k] for k in ("error", "error_type", "screenshot", "url", "checks") if again.get(k)})
        for key in ("trace", "screenshot"):
            if again.get(key) and not r.get(key):
                r[key] = again[key]
        if again["outcome"] == "passed":
            r["flaky"] = True  # keep the original failure, but mark it flaky


def _clean_up_again(state: QAState, run_dir: Path, test_dir: Path, shot_dir: Path) -> None:
    """Staging: a retry or a healing re-run of a form test sends the form again AFTER test_cleanup.py ran - what it
    created is removed by running the cleanup once more, at the very end (nothing tagged with the run may stay)."""
    f = run_dir / "created.jsonl"
    if not (test_dir / "test_cleanup.py").exists() or not f.exists() or runctl.stopping():
        return
    latest = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        latest[r.get("tag")] = r.get("status")
    left = [t for t, s in latest.items() if s == "created"]
    if left:
        print(f"  [execution] {len(left)} record(s) were created after the cleanup (by a re-run of a failed test): "
              "cleaning up again ...")
        _run_pytest(state, test_dir, run_dir / "cleanup_again.jsonl", shot_dir / "cleanup_again",
                    select=["test_cleanup.py"], headless=True)


def _rerun_healed(state: QAState, run_dir: Path, test_dir: Path, shot_dir: Path) -> QAState:
    """After Self-Healing: run the repaired tests AND the other tests of the repaired files again, then keep each
    repair or undo it (_repair_verdict). Nothing is called repaired without this run; the first failure is kept."""
    from .failure_analysis import _short_error, classify
    rnd = state.get("heal_round", 1)
    ids = list(state["rerun_only"])
    log = state.get("healing_log", [])
    entries = [h for h in log if h.get("round") == rnd and h["status"] == "pending"]
    before = {r["nodeid"]: r for r in state.get("results", [])}
    related = {f: [n for n in _related(state.get("results", []), f, test_dir) if n not in ids]
               for f in {h["file"] for h in entries}}
    extra = sorted({n for ns in related.values() for n in ns})
    print(f"  [execution] running {len(ids)} repaired test(s) again, with {len(extra)} other test(s) of the same "
          f"file(s) (healing round {rnd}) ...")
    _run_pytest(state, test_dir, run_dir / f"heal_{rnd}.jsonl", shot_dir / f"heal_{rnd}", select=ids + extra,
                traces=True)
    fresh = {r["nodeid"]: r for r in _read(run_dir / f"heal_{rnd}.jsonl")}
    _relative(list(fresh.values()), run_dir)

    for h in entries:  # keep it, or undo it - from the evidence of this run
        r = fresh.get(h["nodeid"])
        h["related"] = related.get(h["file"], [])[:60]
        broke = [n for n in h["related"] if (before.get(n) or {}).get("outcome") == "passed"
                 and (fresh.get(n) or {}).get("outcome") in ("failed", "error")]
        h["status"], h["why"] = _repair_verdict(r, broke)
        h["rerun"] = {"outcome": r["outcome"] if r else "not run", "error": _short_error(r.get("error")) if r else "",
                      "category": classify(r)[0] if r and r["outcome"] in ("failed", "error") else ""}
    by_file: dict[str, list[dict]] = {}
    for h in entries:
        by_file.setdefault(h["file"], []).append(h)
    for f, hs in by_file.items():
        if any(h["status"] == "reverted" for h in hs):
            _undo(test_dir, run_dir, f, hs)
    undone = {h["nodeid"] for h in entries if h["status"] in ("reverted", "still failing")}
    # the tests that ran with a repair that is now undone (also flows calling a repaired steps module): first result
    stale = undone | {n for h in entries if h["status"] == "reverted" for n in h["related"]}

    results = []
    for r in state.get("results", []):
        new = fresh.pop(r["nodeid"], None)
        if new is None:
            results.append(r)
        elif r["nodeid"] in stale:
            results.append(r)  # the repair was undone: the first result stands
        elif r["nodeid"] in ids:
            new["healed_round"] = rnd
            new["before_healing"] = {k: r.get(k) for k in ("outcome", "error", "screenshot", "trace")}  # kept
            results.append(new)
        else:
            new["rerun_with_repair"] = rnd  # another test of a repaired file, run again with the repair
            results.append(new)
    results += list(fresh.values())
    _clean_up_again(state, run_dir, test_dir, shot_dir)

    (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (run_dir / "healing_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")  # (with the verdicts)
    count = {s: sum(1 for h in entries if h["status"] == s) for s in ("healed", "repaired", "reverted", "still failing")}
    return {"results": results, "rerun_only": [], "healing_log": log,
            "unhealable": sorted(set(state.get("unhealable", [])) | undone),
            "log": state.get("log", []) + [
                f"Execution (healing round {rnd}): {len(ids)} repaired test(s) and {len(extra)} other test(s) of the same "
                f"file(s) ran again - {count['healed']} pass now, {count['repaired']} now fail on a real check (kept), "
                f"{count['reverted'] + count['still failing']} undone or still failing."]}


def _completed_outcomes(results: list[dict]) -> dict[str, dict]:
    """Nodeid -> result for tests that already answered (resume must not re-run or duplicate them)."""
    done = {}
    for r in results:
        nid = r.get("nodeid")
        if nid and r.get("outcome") in ("passed", "failed", "error", "inconclusive", "skipped", "blocked"):
            done[nid] = r
    return done


def _collect_nodeids(test_dir: Path) -> list[str]:
    """Collect pytest nodeids offline (no browser) so a resumed run can skip completed work."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
             "--rootdir", str(test_dir.resolve()), str(test_dir.resolve())],
            cwd=str(test_dir.resolve()), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except (OSError, subprocess.TimeoutExpired):
        return []
    ids = []
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if "::" in line and not line.startswith("=") and " error" not in line.lower():
            ids.append(line.split()[0] if " " in line else line)
    return ids


def execution_agent(state: QAState) -> QAState:
    if state.get("target_type") == "mobile":
        from ..android_pipeline import _execute_mobile
        return _execute_mobile(state)
    if state.get("contract_only"):
        from ..qa_web import execute_pipeline_contracts

        output = execute_pipeline_contracts(state)
        results = (list(state.get("results") or []) if state.get("resuming") else []) + output["results"]
        cases = output["test_cases"]
        for case in cases:
            result = next((r for r in results if r.get("contract_id") == case.get("contract_id")), None)
            if result:
                case["execution_status"] = {"passed": "Passed", "failed": "Failed", "blocked": "Blocked"}.get(
                    result.get("outcome"), "Inconclusive")
                case["actual_result"] = result.get("error") or result.get("outcome", "unknown")
        run_dir = Path(state["run_dir"])
        (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        (run_dir / "execution.json").write_text(json.dumps({"tests": len(results), "timed_out": False,
                                                               "stopped": False}, indent=2), encoding="utf-8")
        passed = sum(r.get("outcome") == "passed" for r in results)
        failed = sum(r.get("outcome") in ("failed", "error") for r in results)
        note = f"Contract-only execution: {len(results)} approved flow(s) - {passed} passed, {failed} failed; no other tests ran."
        print("  [execution] " + note)
        return {"results": results, "test_cases": cases, "log": state.get("log", []) + [note]}
    run_dir = Path(state["run_dir"])
    test_dir = run_dir / "generated_tests"
    shot_dir = run_dir / "failure_screenshots"
    shot_dir.mkdir(exist_ok=True)

    if state.get("rerun_only"):
        return _rerun_healed(state, run_dir, test_dir, shot_dir)

    # Resume: keep completed results from an interrupted suite; only run pending nodeids (no duplicate writes).
    from .failure_analysis import load_saved_results
    prior = _completed_outcomes(load_saved_results(run_dir) or state.get("results") or [])
    select = None
    if prior:
        collected = _collect_nodeids(test_dir)
        pending = [n for n in collected if n not in prior] if collected else []
        if collected and not pending:
            print(f"  [execution] resume: all {len(prior)} collected test(s) already have results - skipping suite",
                  flush=True)
            results = list(prior.values())
            info = {"timed_out": False, "stopped": False, "returncode": 0, "sandbox": "resume-kept",
                    "resume_kept": len(prior)}
            (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            (run_dir / "execution.json").write_text(json.dumps(dict(info, tests=len(results)), indent=2),
                                                    encoding="utf-8")
            note = (f"Execution resume: kept {len(prior)} completed result(s); no pending tests — "
                    "did not re-run or duplicate run-owned writes.")
            print("  [execution] " + note)
            return {"results": results, "test_cases": state.get("test_cases", []),
                    "log": state.get("log", []) + [note]}
        if pending:
            select = pending
            print(f"  [execution] resume: keeping {len(prior)} completed result(s); "
                  f"running {len(pending)} pending test(s)", flush=True)
        else:
            print(f"  [execution] resume: {len(prior)} prior result(s) on disk; could not collect pending ids — "
                  "full suite will merge without dropping completed work", flush=True)

    print("  [execution] running generated tests in the sandbox ...")
    if not settings.headless:
        print("  [execution] ONE Chrome window shows every test, one after another: the journeys first, then the "
              "features and page checks, the small checks (input values, links) last")
        print(f"  [execution] watched browser: fitted to the screen, action captions on, slow motion "
              f"{_watched_slow_mo_ms()} ms")
        print("  [execution] note: visible Chrome is serial (one window); hidden runs use TEST_WORKERS in parallel")
    results_file = run_dir / (f"results.resume-{uuid.uuid4().hex[:8]}.jsonl" if state.get("resuming") else "results.jsonl")
    if state.get("resuming") and settings.writes_ok:
        raise RuntimeError("Resume with writes requires reconciliation of interrupted run-owned records. "
                           "Resume read-only or review created.jsonl and start a fresh authorized write run.")
    info = _run_pytest(state, test_dir, results_file, shot_dir, select=select)
    by_id = dict(prior)
    for result in _read(results_file):
        if result.get("nodeid"):
            by_id[result["nodeid"]] = result
    results = list(by_id.values())

    # Bounded retries (TEST_RETRIES): run failed tests again, with a trace. Pass on a retry => flaky (the first
    # failure is kept); failed again for another reason => the retry's failure is reported (see _merge_retry).
    for attempt in range(1, settings.test_retries + 1):
        failed_ids = [r["nodeid"] for r in results if r["outcome"] in ("failed", "error") and not r.get("flaky")
                      and r["test"] != "(collection)"]
        if not failed_ids or info["timed_out"] or runctl.stopping():
            break
        print(f"  [execution] retry {attempt}: re-running {len(failed_ids)} failed tests (with traces) ...")
        name = "rerun" if attempt == 1 else f"rerun{attempt}"
        _run_pytest(state, test_dir, run_dir / f"{name}.jsonl", shot_dir / name, select=failed_ids, traces=True)
        # (watching: in the same one window, after the first try - hidden: in parallel)
        _merge_retry(results, {r["nodeid"]: r for r in _read(run_dir / f"{name}.jsonl")})
    _clean_up_again(state, run_dir, test_dir, shot_dir)

    from ..qa_web import execute_pipeline_contracts
    contract_output = execute_pipeline_contracts(state)
    if contract_output["results"]:
        results.extend(contract_output["results"])
        state = {**state, "test_cases": state.get("test_cases", []) + contract_output["test_cases"]}
    _relative(results, run_dir)
    # the website stopped answering during the tests (conftest: those tests are NOT RUN, never 'failed')
    down = [r for r in results if (r.get("error") or "").startswith("Not run: the website did not answer")]
    if down:
        since = re.search(r"since (\d\d:\d\d)", down[0]["error"])
        info["website_down"] = {"tests": len(down), "since": since.group(1) if since else ""}
    (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (run_dir / "execution.json").write_text(json.dumps(dict(info, tests=len(results)), indent=2), encoding="utf-8")
    passed = sum(r["outcome"] == "passed" for r in results)
    failed = sum(r["outcome"] in ("failed", "error") for r in results)
    skipped = sum(r["outcome"] == "skipped" for r in results)
    unclear = sum(r["outcome"] == "inconclusive" for r in results)
    flaky = sum(bool(r.get("flaky")) for r in results)
    log = state.get("log", []) + [
        f"Execution: {len(results)} tests run — {passed} passed, {failed} failed ({flaky} flaky), {skipped} skipped"
        + (f", {unclear} inconclusive (checked nothing)" if unclear else "") + "."
        + (f" THE WEBSITE STOPPED ANSWERING (since {info['website_down']['since']}): {len(down)} test(s) could not "
           "run - run again when it is back." if down else "")
        + (" THE RUN WAS STOPPED BY ITS TIME LIMIT." if info["timed_out"] else "")
        + (f" The test run was stopped early ({runctl.reason()}): the remaining tests did not run."
           if info.get("stopped") else "")]
    return {"results": results, "test_cases": state.get("test_cases", []), "log": log}
