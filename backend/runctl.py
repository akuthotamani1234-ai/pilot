"""Run control: stopping a run on purpose, so it still ends with a report.

A run can be asked to stop by
  user_stop        the web UI's Stop button (it writes runs/<run>/STOP, a watcher thread sees it)
  ctrl_c           Ctrl+C in the terminal (main.py's signal handler)
  run_time_limit   RUN_TIME_LIMIT_MIN is over (a timer)
The agents check stopping() at safe points (the crawl loop, between test-run slices, before an AI call) and return
what they have, so main.py can write the report with everything done so far. If an agent does not return within
GRACE_S of the request (a stuck call), the main thread is interrupted (KeyboardInterrupt) - the report is then written
from the state after the last finished stage.

Soft reserve (ANALYSIS_RESERVE_S + REPORT_RESERVE_S): when remaining wall-clock is inside that window,
should_stop_heavy_work() is True so discovery stops starting heavy interactions and execution shortens —
failure analysis and report still run. Measure phase durations before raising reserve defaults.
"""
import _thread
import sys
import threading
import time
from pathlib import Path

GRACE_S = 60

_stop = threading.Event()
_why = {"kind": "", "reason": ""}
_timers: list[threading.Timer] = []
_started = 0.0
_limit_s = 0.0


def request_stop(kind: str, reason: str) -> None:
    """Ask the run to stop (the first request's reason is kept)."""
    if _stop.is_set():
        return
    _why.update(kind=kind, reason=reason)
    _stop.set()
    print(f"\n  [run] stopping: {reason} - writing the report with what was done so far", flush=True)
    t = threading.Timer(GRACE_S, _thread.interrupt_main)  # (cancelled by finished() when the run ended in time)
    t.daemon = True
    t.start()
    _timers.append(t)


def stopping() -> bool:
    return _stop.is_set()


def kind() -> str:
    return _why["kind"]


def reason() -> str:
    return _why["reason"]


def remaining_s() -> float | None:
    """Seconds left under RUN_TIME_LIMIT_MIN, or None when the run has no wall-clock limit."""
    if not _limit_s or _started <= 0:
        return None
    return max(0.0, _limit_s - (time.time() - _started))


def reserve_budget_s() -> float:
    """Soft slice kept for deterministic analysis + report near the run end (env knobs; measure before raising)."""
    from .config import settings
    return max(0, int(settings.analysis_reserve_s)) + max(0, int(settings.report_reserve_s))


def should_stop_heavy_work() -> bool:
    """True on hard stop, or when remaining time is inside the analysis+report reserve.

    Heavy discovery interactions and starting a long suite should yield; analysis/report must still run.
    """
    if stopping():
        return True
    rem = remaining_s()
    if rem is None:
        return False
    budget = reserve_budget_s()
    return budget > 0 and rem <= budget


def _keep_awake(on: bool) -> None:
    """Windows: the PC does not go to sleep by itself while a run is going (the screen may still turn off). A laptop
    that slept in the middle of the tests stopped every browser and woke up past the run's time limit (OrangeHRM,
    Nov 2: 92 minutes asleep). Closing the lid still follows the PC's own power settings."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        es_continuous, es_system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | (es_system_required if on else 0))
    except (AttributeError, OSError):
        pass


def start_watchers(run_dir: Path, limit_min: float) -> None:
    """The run time limit (a timer) and the STOP file of the web UI (a thread that looks for it every second)."""
    global _started, _limit_s
    _keep_awake(True)
    _started = time.time()
    _limit_s = (limit_min * 60) if limit_min and limit_min > 0 else 0.0
    if _limit_s:
        t = threading.Timer(_limit_s, request_stop,
                            args=("run_time_limit", f"the run hit its time limit of {limit_min:g} min (RUN_TIME_LIMIT_MIN)"))
        t.daemon = True
        t.start()
        _timers.append(t)
    stop_file = Path(run_dir) / "STOP"

    def watch():
        while not _stop.wait(1):
            if stop_file.exists():
                request_stop("user_stop", "you stopped the test")
                return
    threading.Thread(target=watch, daemon=True, name="qa-stop-watch").start()


def finished() -> None:
    """The run is over: no timer may interrupt the report or the exit any more (and the PC may sleep again)."""
    for t in _timers:
        t.cancel()
    _timers.clear()
    _keep_awake(False)


def reset() -> None:
    """A fresh start (tests run several pipelines in one process)."""
    global _started, _limit_s
    finished()
    _stop.clear()
    _why.update(kind="", reason="")
    _started = 0.0
    _limit_s = 0.0
