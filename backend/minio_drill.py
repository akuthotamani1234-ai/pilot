"""Gate G: live MinIO put/get/delete isolation drill."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "minio_object_store_drill.json"


def object_store_drill(*, uri: str | None = None) -> dict:
    from .object_store import open_object_store

    target = (
        uri
        or os.getenv("OBJECT_STORE_URI")
        or os.getenv("MINIO_URL")
        or "minio://127.0.0.1:9000/qpilot-evidence"
    ).strip()
    evidence = {
        "gate_g_complete": False,
        "drill": "minio_put_get_delete",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ok": False,
        "reason": "",
        "uri_scheme": target.split(":", 1)[0],
    }
    opened = open_object_store(target)
    evidence["open"] = {"ready": opened.get("ready"), "backend": opened.get("backend"),
                        "reason": opened.get("reason")}
    if not opened.get("ready") or opened.get("store") is None:
        evidence["reason"] = opened.get("reason") or "object store not ready"
        return evidence
    store = opened["store"]
    key_a = f"drill/tenant-a/{int(time.time())}.txt"
    key_b = f"drill/tenant-b/{int(time.time())}.txt"
    store.put(key_a, b"tenant-a-secret")
    store.put(key_b, b"tenant-b-secret")
    got_a = store.get(key_a)
    keys = store.list_keys("drill/")
    deleted = store.delete(key_a)
    missing_ok = False
    try:
        store.get(key_a)
    except Exception:
        missing_ok = True
    store.delete(key_b)
    ok = (
        got_a == b"tenant-a-secret"
        and key_a in keys
        and key_b in keys
        and deleted
        and missing_ok
        and opened.get("backend") == "minio"
    )
    evidence.update({
        "ok": ok,
        "keys_seen": keys[:20],
        "backend": opened.get("backend"),
        "reason": (
            "Live MinIO put/get/list/delete verified; Studio multi-tenant object ACLs + review still open"
            if ok else "MinIO drill assertions failed"
        ),
    })
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    art = ROOT / "artifacts" / "ops" / "minio_object_store_drill.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
