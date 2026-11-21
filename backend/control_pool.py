"""Control-learning pool: a few extra browsers that try independent controls of a page at the same time.

Each worker is a thread with its own Playwright, browser and context (the same request guard, start scripts and
login state as the crawl's own browser). A job is `fn(page, worker)`; results come back in job order. A worker that
fails to start or crashes is reported in `errors`, and its jobs come back as exceptions instead of being lost.
"""
from __future__ import annotations

import queue
import threading


class ControlPool:
    def __init__(self, size: int, make_context, *, on_page=None, worker_info=None, headless: bool = True):
        self.size = max(1, int(size))
        self._make_context = make_context        # (browser) -> context, called in the worker's own thread
        self._on_page = on_page                  # (page, index) -> None: listeners for the worker's page
        self._worker_info = worker_info          # (index) -> dict passed to every job of that worker
        self._headless = headless
        self._jobs: queue.Queue = queue.Queue()
        self._ready = threading.Barrier(self.size + 1)
        self.errors: list[str] = []
        self.started = 0
        self._lock = threading.Lock()
        self._threads = [threading.Thread(target=self._run, args=(i + 1,), name=f"learner-{i + 1}", daemon=True)
                         for i in range(self.size)]
        for t in self._threads:
            t.start()
        try:
            self._ready.wait(timeout=60)
        except threading.BrokenBarrierError:
            self.errors.append("a learner browser did not start within 60 s")

    @property
    def capacity(self) -> int:
        """How many tries can run at once (0 = the pool is unusable: the crawl tries controls itself)."""
        return self.started

    def _run(self, index: int) -> None:
        pw = browser = None
        try:
            from playwright.sync_api import sync_playwright

            from .config import settings
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=self._headless, args=["--disable-dev-shm-usage"])
            context = self._make_context(browser)
            context.set_default_timeout(10000)
            context.set_default_navigation_timeout(settings.page_timeout_ms)
            page = context.new_page()
            if self._on_page:
                self._on_page(page, index)
            info = self._worker_info(index) if self._worker_info else {}
            with self._lock:
                self.started += 1
        except Exception as exc:
            with self._lock:
                self.errors.append(f"learner {index} could not start: {type(exc).__name__}: {str(exc)[:200]}")
            page = info = None
        try:
            self._ready.wait(timeout=60)
        except threading.BrokenBarrierError:
            pass
        try:
            while True:
                job = self._jobs.get()
                if job is None:
                    return
                fn, slot, done = job
                if page is None:  # (this worker never started: hand the job back as an error, never drop it)
                    slot.append(RuntimeError("learner browser unavailable"))
                    done.release()
                    continue
                try:
                    slot.append(fn(page, info))
                except BaseException as exc:
                    with self._lock:
                        self.errors.append(f"learner {index}: {type(exc).__name__}: {str(exc)[:200]}")
                    slot.append(exc)
                    try:  # a crashed page is replaced, so the next job starts clean
                        page.close()
                    except Exception:
                        pass
                    try:
                        page = page.context.new_page()
                        if self._on_page:
                            self._on_page(page, index)
                    except Exception:
                        page = None
                finally:
                    done.release()
        finally:
            try:
                if browser is not None:
                    browser.close()
            finally:
                if pw is not None:
                    pw.stop()

    def run(self, jobs: list) -> list:
        """Run jobs (fn(page, worker)) at once; results in job order (an exception stands for a failed job)."""
        slots, done = [[] for _ in jobs], threading.Semaphore(0)
        for fn, slot in zip(jobs, slots):
            self._jobs.put((fn, slot, done))
        for _ in jobs:
            done.acquire()
        return [slot[0] if slot else RuntimeError("no result") for slot in slots]

    def close(self) -> None:
        for _ in self._threads:
            self._jobs.put(None)
        for t in self._threads:
            t.join(timeout=30)
