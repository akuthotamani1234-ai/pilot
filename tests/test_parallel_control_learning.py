"""Learner browsers try a page's controls at the same time and learn exactly what the crawl's own browser learns
one by one (same controls, same effects; a nested control's menu is opened first, as the crawl does)."""
import http.server
import json
import threading

import pytest

from backend.config import settings

PAGE = """<title>Panel</title><h1>Panel</h1>
<button id=a onclick="document.getElementById('m').textContent='Saved A'">Show A</button>
<button id=b onclick="document.getElementById('m').textContent='Saved B'">Show B</button>
<button id=c onclick="document.getElementById('m').textContent='Saved C'">Show C</button>
<button id=d onclick="document.getElementById('m').textContent='Saved D'">Show D</button>
<button id=e onclick="location.href='/two'">Go to two</button>
<button id=menu onclick="document.getElementById('sub').hidden=false">Open menu</button>
<div id=sub hidden><button id=deep onclick="document.getElementById('m').textContent='Deep done'">Deep action</button></div>
<p id=m role=status></p>"""


def _serve():
    class Site(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = (PAGE if self.path == "/" else "<title>Two</title><h1>Two</h1>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def _learned(tmp_path, monkeypatch, workers):
    from backend.agents import discovery
    monkeypatch.setattr(settings, "headless", True)
    monkeypatch.setattr(settings, "max_pages", 1)
    monkeypatch.setattr(settings, "explore_workers", workers)
    srv, url = _serve()
    run = tmp_path / f"w{workers}"
    run.mkdir()
    try:
        out = discovery.discovery_agent({"url": url, "run_dir": str(run), "site_key": "t", "log": []})
    finally:
        srv.shutdown()
    home = out["app_map"][0]
    effects = {(b["control"], b["effect"], b.get("message") or "", (b.get("to") or "").rsplit("/", 1)[-1])
               for b in home.get("behaviour", [])}
    return run, effects


def test_learners_learn_the_same_as_one_browser(tmp_path, monkeypatch):
    _run0, sequential = _learned(tmp_path, monkeypatch, 0)
    run3, parallel = _learned(tmp_path, monkeypatch, 3)
    assert parallel == sequential
    names = {c for c, *_ in parallel}
    assert {"Show A", "Show B", "Show C", "Show D", "Go to two", "Open menu", "Deep action"} <= names
    assert any(e == "navigates" for _c, e, *_ in parallel)
    # the learners really did the work: each learner that tried a control has its own timeline
    timelines = list(run3.glob("events.discovery-*.learner-*.jsonl"))
    assert timelines
    events = [json.loads(line) for f in timelines for line in f.read_text(encoding="utf-8").splitlines()]
    tried = {e["text"] for e in events if e["status"] == "running"}
    assert any("Show A" in t or "Show B" in t for t in tried)
    # a nested control is tried by a learner too: it opens the menu that reveals it first, like the crawl does
    assert any("Deep action" in t for t in tried)
    assert any("Open menu" in t for t in tried)


def test_a_pool_that_cannot_start_falls_back_to_one_browser(tmp_path, monkeypatch):
    from backend import control_pool
    real = control_pool.ControlPool

    class Broken(real):
        def __init__(self, size, make_context, **kw):
            super().__init__(size, lambda b: (_ for _ in ()).throw(RuntimeError("no browser")), **kw)
    monkeypatch.setattr(control_pool, "ControlPool", Broken)
    _run, effects = _learned(tmp_path, monkeypatch, 2)
    assert {"Show A", "Deep action"} <= {c for c, *_ in effects}


@pytest.fixture(autouse=True)
def _no_live_frames(monkeypatch):
    monkeypatch.setenv("QA_LIVE_FRAMES", "false")
