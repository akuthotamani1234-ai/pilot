"""Gate C: AdminPortal fixture create → remote_delete cleanup confirmation.

Localhost AdminPortal only. Broader live portal paths still open —
gate_c_complete stays False.
"""
from __future__ import annotations

import http.client
import json
import time
import urllib.parse
from pathlib import Path

from .data_lifecycle import Lifecycle, admin_portal_delete, save_lifecycle, to_state

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "admin_portal_lifecycle_drill.json"


def _linked_portal() -> dict:
    return {
        "gate_c_complete": False,
        "ok": False,
        "drill": "admin_portal_lifecycle_cleanup",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_admin_portal_lifecycle_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "admin_portal_lifecycle_drill.json"
    work = Path(ops_dir) / "admin_portal_lifecycle_work" if ops_dir else (
        ROOT / "artifacts" / "ops" / "admin_portal_lifecycle_work"
    )
    if (folder_is_linked(dest) or folder_is_linked(dest / out_name) or folder_is_linked(work)):
        return _linked_portal()

    from tests.admin_portal import AdminPortal

    portal = AdminPortal().start()
    work.mkdir(parents=True, exist_ok=True)
    run_dir = work / f"run_{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)
    user_id = None
    cleanup: dict = {}
    try:
        body = urllib.parse.urlencode({
            "name": "Ops Lifecycle Drill",
            "email": "ops-lifecycle@example.com",
            "role": "Viewer",
            "age": "31",
        }).encode()
        conn = http.client.HTTPConnection("127.0.0.1", portal.port, timeout=10)
        conn.request(
            "POST",
            "/users/new",
            body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp = conn.getresponse()
        loc = resp.getheader("Location") or ""
        resp.read()
        conn.close()
        if "created=" in loc:
            user_id = loc.split("created=")[-1].split("&")[0]
        if not user_id and portal.users:
            user_id = str(portal.users[-1]["id"])
        if not user_id:
            raise RuntimeError("AdminPortal create did not yield a user id")

        life = Lifecycle(run_id=run_dir.name, environment="test")
        life.prepare(1)
        life._by_worker[1] = [{
            "tag": f"user:{user_id}",
            "kind": "account",
            "state": "ready",
            "run_id": run_dir.name,
            "remote_id": user_id,
            "source": "admin_portal",
        }]
        adapter = admin_portal_delete(portal.url)
        cleanup = life.cleanup_confirmed(1, remote_delete=adapter)
        save_lifecycle(run_dir, life)
        still_present = any(int(u["id"]) == int(user_id) for u in portal.users)
        confirmed_n = len(cleanup.get("confirmed") or [])
        failed_n = len(cleanup.get("failed") or [])
        evidence = {
            "gate_c_complete": False,
            "drill": "admin_portal_lifecycle_cleanup",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "fixture": "AdminPortal",
            "user_id": str(user_id),
            "confirmed": confirmed_n,
            "failed": failed_n,
            "complete": bool(cleanup.get("complete")),
            "user_removed": not still_present,
            "sample_proofs": [
                row.get("cleanup_proof") for row in (cleanup.get("confirmed") or [])[:5]
            ],
            "ok": (
                confirmed_n > 0
                and failed_n == 0
                and bool(cleanup.get("complete"))
                and not still_present
            ),
            "state_run_id": to_state(life).get("run_id"),
            "reason": (
                "AdminPortal create→remote_delete cleanup confirmed on localhost fixture; "
                "broader live portal paths still open"
            ),
        }
    finally:
        try:
            portal.stop()
        except Exception:
            pass

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name) or folder_is_linked(work):
        return _linked_portal()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_portal()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
