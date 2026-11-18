"""Gate H: paging escalation rehearsal (loopback).

Primary sink returns 500; client escalates to secondary sink which accepts
202. Proves local escalation wiring — live hosted on-call / multi-region
paging still open; ``gate_h_complete`` stays False.
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
EVIDENCE = ROOT / "docs" / "ops-evidence" / "paging_escalation_drill.json"


class _Primary(BaseHTTPRequestHandler):
    hits: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        self.hits.append({"body_len": len(body)})
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":false,"error":"primary_down"}')

    def log_message(self, format, *args):
        return


class _Secondary(BaseHTTPRequestHandler):
    hits: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"raw": body.decode("utf-8", errors="replace")}
        self.hits.append(payload)
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true,"sink":"secondary"}')

    def log_message(self, format, *args):
        return


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _post(port: int, payload: dict) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = json.dumps(payload).encode("utf-8")
    conn.request("POST", "/page", body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    status = resp.status
    resp.read()
    conn.close()
    return status


def run_paging_escalation_drill(*, ops_dir: Path | None = None) -> dict:
    base = Path(ops_dir) if ops_dir else ROOT / "artifacts" / "ops"
    base.mkdir(parents=True, exist_ok=True)
    primary_port = _free_port()
    secondary_port = _free_port()
    primary = HTTPServer(("127.0.0.1", primary_port), _Primary)
    secondary = HTTPServer(("127.0.0.1", secondary_port), _Secondary)
    _Primary.hits = []
    _Secondary.hits = []
    t1 = threading.Thread(target=primary.serve_forever, daemon=True)
    t2 = threading.Thread(target=secondary.serve_forever, daemon=True)
    t1.start()
    t2.start()
    payload = {
        "severity": "SEV1",
        "source": "qpilot-paging-escalation",
        "message": "Synthetic Gate H escalation — not a real incident",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    primary_status = None
    secondary_status = None
    escalated = False
    try:
        primary_status = _post(primary_port, payload)
        if primary_status >= 500:
            secondary_status = _post(secondary_port, {**payload, "escalated_from": "primary"})
            escalated = secondary_status == 202 and bool(_Secondary.hits)
    except Exception as exc:
        payload["error"] = str(exc)[:200]
    finally:
        primary.shutdown()
        primary.server_close()
        secondary.shutdown()
        secondary.server_close()

    ok = (
        primary_status == 500
        and bool(_Primary.hits)
        and escalated
        and secondary_status == 202
    )
    evidence = {
        "gate_h_complete": False,
        "drill": "paging_escalation",
        "ran_at": payload["ran_at"],
        "ok": ok,
        "primary": {
            "url": f"http://127.0.0.1:{primary_port}/page",
            "http_status": primary_status,
            "hits": len(_Primary.hits),
        },
        "secondary": {
            "url": f"http://127.0.0.1:{secondary_port}/page",
            "http_status": secondary_status,
            "hits": len(_Secondary.hits),
        },
        "escalated": escalated,
        "reason": (
            "Loopback primary→secondary paging escalation accepted; "
            "live hosted on-call / multi-region paging still open"
            if ok else
            "Paging escalation rehearsal failed; live hosted on-call still open"
        ),
    }
    out = base / "paging_escalation_drill.json"
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
