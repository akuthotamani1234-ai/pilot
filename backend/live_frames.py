"""Live screens: each browser worker's latest real screenshot, for the dashboard's swarm view.

A frame is a small JPEG of the worker's visible page, taken right before the action the event
describes, so the cursor drawn at the event's ``point`` sits on the element the worker is acting on.
Only the newest frame per worker is kept (``live/<worker>.jpg``); it is replaced atomically.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

LIVE_DIR = "live"
_SAFE = re.compile(r"[^a-z0-9-]")
_lock = threading.Lock()
_last: dict[str, float] = {}
_seq: dict[str, int] = {}


def enabled() -> bool:
    return os.environ.get("QA_LIVE_FRAMES", "true").lower() != "false"


def worker_file(worker: str) -> str:
    """The frame's file name for a worker id (only a-z, 0-9 and '-')."""
    name = _SAFE.sub("", str(worker or "").lower())[:40]
    return f"{name or 'worker'}.jpg"


def write_frame(page, run_dir: Path, worker: str, *, min_gap_s: float = 0.35, force: bool = False) -> int | None:
    """Save the worker's visible page as its latest frame. Returns the frame number, or None when skipped."""
    if not enabled():
        return None
    now = time.time()
    with _lock:
        if not force and now - _last.get(worker, 0.0) < min_gap_s:
            return None
        _last[worker] = now
    folder = Path(run_dir) / LIVE_DIR
    try:
        folder.mkdir(parents=True, exist_ok=True)
        data = page.screenshot(type="jpeg", quality=50, timeout=2500, animations="disabled", caret="initial")
        target = folder / worker_file(worker)
        tmp = folder / f".{target.stem}.{uuid.uuid4().hex[:8]}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, target)
    except Exception:
        return None
    with _lock:
        _seq[worker] = _seq.get(worker, 0) + 1
        return _seq[worker]


class EventLog:
    """One worker's durable timeline in the same format the test workers write (``events.*.jsonl``)."""

    def __init__(self, run_dir: Path, worker: str, *, role: str = "", phase: str = "discovery"):
        self.run_dir = Path(run_dir)
        self.worker = worker
        self.role = role
        self.phase = phase
        self._session = uuid.uuid4().hex[:12]
        self._n = 0
        self._t0 = time.time()
        self.path = self.run_dir / f"events.{phase}-{self._session}.{worker}.jsonl"

    def emit(self, text: str, status: str, *, url: str = "", **details) -> None:
        self._n += 1
        value = {"id": f"{self._session}:{self._n}", "timestamp": time.time(), "worker": self.worker,
                 "role": self.role, "phase": self.phase, "test": f"{self.role or 'Agent'} · {self.phase}",
                 "url": url, "nodeid": "", "status": status, "text": str(text)[:500],
                 "elapsed": round(time.time() - self._t0, 2), **details}
        try:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(value) + "\n")
        except OSError:
            pass
