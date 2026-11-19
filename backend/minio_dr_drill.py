"""Gate H: MinIO object-store backup/restore drill (copy → delete → restore).

Live hosted DR / multi-tenant ACLs remain open. Never marks Gate H complete.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "minio_backup_restore_drill.json"


def _linked_dr() -> dict:
    return {
        "gate_h_complete": False,
        "gate_g_complete": False,
        "ok": False,
        "drill": "minio_object_backup_restore",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def object_store_backup_restore_drill(*, uri: str | None = None, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "minio_backup_restore_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_dr()

    from .object_store import open_object_store

    target = (
        uri
        or os.getenv("OBJECT_STORE_URI")
        or os.getenv("MINIO_URL")
        or "minio://127.0.0.1:9000/qpilot-evidence"
    ).strip()
    stamp = int(time.time())
    evidence = {
        "gate_h_complete": False,
        "gate_g_complete": False,
        "drill": "minio_object_backup_restore",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ok": False,
        "reason": "",
        "uri_scheme": target.split(":", 1)[0],
    }
    opened = open_object_store(target)
    evidence["open"] = {
        "ready": opened.get("ready"),
        "backend": opened.get("backend"),
        "reason": opened.get("reason"),
    }
    if not opened.get("ready") or opened.get("store") is None:
        evidence["reason"] = opened.get("reason") or "object store not ready"
        if not _write(evidence, ops_dir):
            return _linked_dr()
        return evidence

    store = opened["store"]
    primary = f"dr/primary/{stamp}.bin"
    backup = f"dr/backup/{stamp}.bin"
    payload = f"qpilot-dr-{stamp}".encode()
    try:
        store.put(primary, payload)
        # Backup = durable second key holding the same bytes.
        store.put(backup, store.get(primary))
        assert store.get(backup) == payload
        store.delete(primary)
        missing = False
        try:
            store.get(primary)
        except Exception:
            missing = True
        # Restore
        store.put(primary, store.get(backup))
        restored = store.get(primary)
        ok = missing and restored == payload and opened.get("backend") == "minio"
        evidence.update({
            "ok": ok,
            "primary_key": primary,
            "backup_key": backup,
            "bytes": len(payload),
            "backend": opened.get("backend"),
            "reason": (
                "Live MinIO backup-key + restore verified; hosted DR / multi-tenant ACLs still open"
                if ok else "MinIO backup/restore assertions failed"
            ),
        })
    except Exception as exc:
        evidence["reason"] = f"MinIO DR drill failed: {exc}"
        evidence["ok"] = False
    finally:
        try:
            store.delete(primary)
            store.delete(backup)
        except Exception:
            pass
    if not _write(evidence, ops_dir):
        return _linked_dr()
    return evidence


def _write(evidence: dict, ops_dir: Path | None) -> bool:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "minio_backup_restore_drill.json"
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return False
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return False
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return True
