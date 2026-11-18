"""Gate H: local paging rehearsal (offline).

Posts a synthetic incident payload to a loopback HTTP sink (or records a dry
payload when no sink is listening). Never claims live on-call paging is proven.
"""
from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "paging_rehearsal.json"


class _Sink(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"raw": body.decode("utf-8", errors="replace")}
        self.received.append(payload)
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format, *args):
        return


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run_paging_rehearsal(*, ops_dir: Path | None = None) -> dict:
    """Spin a loopback sink, POST a SEV2 page, record whether it was accepted."""
    base = Path(ops_dir) if ops_dir else ROOT / "artifacts" / "ops"
    base.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _Sink)
    _Sink.received = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    payload = {
        "severity": "SEV2",
        "source": "qpilot-ops-paging-rehearsal",
        "message": "Synthetic Gate H paging rehearsal — not a real incident",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    ok = False
    status = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps(payload).encode("utf-8")
        conn.request("POST", "/page", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()
        ok = status == 202 and bool(_Sink.received)
    except Exception as exc:
        payload["error"] = str(exc)
    finally:
        server.shutdown()
        server.server_close()

    evidence = {
        "gate_h_complete": False,
        "drill": "paging_rehearsal",
        "ran_at": payload["ran_at"],
        "ok": ok,
        "sink": f"http://127.0.0.1:{port}/page",
        "http_status": status,
        "received_count": len(_Sink.received),
        "reason": (
            "Loopback paging sink accepted synthetic SEV2; live hosted on-call/paging still open"
            if ok else
            "Paging rehearsal failed to deliver to loopback sink"
        ),
    }
    out = base / "paging_rehearsal.json"
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
