"""Gate H: paging acknowledge → resolve lifecycle (loopback).

Pages a sink, acknowledges the incident, then resolves it. Proves local
ack/resolve wiring — live hosted on-call paging still open;
``gate_h_complete`` stays False.
"""
from __future__ import annotations

import http.client
import json
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "paging_ack_drill.json"


class _Oncall(BaseHTTPRequestHandler):
    state: dict = {"pages": [], "acks": [], "resolves": []}

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {}
        if self.path.endswith("/page"):
            incident = str(payload.get("incident_id") or uuid.uuid4())
            self.state["pages"].append({"incident_id": incident, **payload})
            self._json(202, {"ok": True, "incident_id": incident, "status": "paged"})
            return
        if self.path.endswith("/ack"):
            self.state["acks"].append(payload)
            self._json(200, {"ok": True, "status": "acked"})
            return
        if self.path.endswith("/resolve"):
            self.state["resolves"].append(payload)
            self._json(200, {"ok": True, "status": "resolved"})
            return
        self._json(404, {"ok": False})

    def _json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):
        return


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = json.dumps(payload).encode("utf-8")
    conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    raw = resp.read()
    status = resp.status
    conn.close()
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        data = {}
    return status, data


def _linked_ack() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "paging_ack",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_paging_ack_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "paging_ack_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_ack()

    port = _free_port()
    _Oncall.state = {"pages": [], "acks": [], "resolves": []}
    server = HTTPServer(("127.0.0.1", port), _Oncall)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        page_status, page_body = _post(
            port, "/page",
            {"incident_id": incident_id, "severity": "primary", "summary": "qpilot-ack-drill"},
        )
        ack_status, ack_body = _post(
            port, "/ack",
            {"incident_id": incident_id, "actor": "oncall-primary"},
        )
        resolve_status, resolve_body = _post(
            port, "/resolve",
            {"incident_id": incident_id, "actor": "oncall-primary", "note": "mitigated"},
        )
        ok = (
            page_status == 202
            and ack_status == 200
            and resolve_status == 200
            and page_body.get("incident_id") == incident_id
            and len(_Oncall.state["pages"]) == 1
            and len(_Oncall.state["acks"]) == 1
            and len(_Oncall.state["resolves"]) == 1
        )
        evidence = {
            "gate_h_complete": False,
            "drill": "paging_ack",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "incident_id": incident_id,
            "page_status": page_status,
            "ack_status": ack_status,
            "resolve_status": resolve_status,
            "lifecycle": ["page", "ack", "resolve"],
            "ok": ok,
            "reason": (
                "Loopback paging ack→resolve lifecycle ok; "
                "live hosted on-call paging still open"
                if ok else
                "Paging ack→resolve lifecycle failed; hosted on-call still open"
            ),
        }
    finally:
        server.shutdown()
        thread.join(timeout=2)

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_ack()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_ack()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
