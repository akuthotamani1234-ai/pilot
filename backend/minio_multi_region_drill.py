"""Gate H: MinIO dual-bucket (region-a / region-b) failover rehearsal.

Puts an object in ``qpilot-region-a``, replicates to ``qpilot-region-b``,
deletes the primary, and reads from the secondary. Local multi-bucket
rehearsal only — hosted multi-region object DR still open;
``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "minio_multi_region_drill.json"
REGION_A = "qpilot-region-a"
REGION_B = "qpilot-region-b"


def _base_uri() -> str:
    return (
        os.getenv("OBJECT_STORE_URI")
        or os.getenv("MINIO_URL")
        or "minio://127.0.0.1:9000/qpilot-evidence"
    ).strip()


def _uri_for_bucket(base: str, bucket: str) -> str:
    parsed = urlparse(base)
    # minio://host:port/bucket  or http(s)://host:port/bucket
    return urlunparse(parsed._replace(path="/" + bucket))


def _linked_minio() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "minio_dual_bucket_failover",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_minio_multi_region_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / "minio_multi_region_drill.json"):
        return _linked_minio()

    from .object_store import open_object_store

    base = _base_uri()
    uri_a = _uri_for_bucket(base, REGION_A)
    uri_b = _uri_for_bucket(base, REGION_B)
    stamp = int(time.time())
    key = f"dr/multi-region/{stamp}.bin"
    payload = f"qpilot-mr-{stamp}".encode()
    ran_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    evidence: dict = {
        "gate_h_complete": False,
        "drill": "minio_dual_bucket_failover",
        "ran_at": ran_at,
        "ok": False,
        "region_a": REGION_A,
        "region_b": REGION_B,
        "key": key,
    }
    opened_a = open_object_store(uri_a)
    opened_b = open_object_store(uri_b)
    evidence["open_a"] = {
        "ready": opened_a.get("ready"),
        "backend": opened_a.get("backend"),
        "reason": opened_a.get("reason"),
    }
    evidence["open_b"] = {
        "ready": opened_b.get("ready"),
        "backend": opened_b.get("backend"),
        "reason": opened_b.get("reason"),
    }
    if not opened_a.get("ready") or opened_a.get("store") is None:
        evidence["reason"] = opened_a.get("reason") or "region-a object store not ready"
        if not _write(evidence, ops_dir):
            return _linked_minio()
        return evidence
    if not opened_b.get("ready") or opened_b.get("store") is None:
        evidence["reason"] = opened_b.get("reason") or "region-b object store not ready"
        if not _write(evidence, ops_dir):
            return _linked_minio()
        return evidence

    store_a = opened_a["store"]
    store_b = opened_b["store"]
    try:
        store_a.put(key, payload)
        # Replicate A → B
        store_b.put(key, store_a.get(key))
        assert store_b.get(key) == payload
        store_a.delete(key)
        missing = False
        try:
            store_a.get(key)
        except Exception:
            missing = True
        # Failover read from region-b
        restored = store_b.get(key)
        ok = (
            missing
            and restored == payload
            and opened_a.get("backend") == "minio"
            and opened_b.get("backend") == "minio"
        )
        evidence.update({
            "ok": ok,
            "bytes": len(payload),
            "failover_read_ok": restored == payload,
            "primary_deleted": missing,
            "reason": (
                "Local MinIO dual-bucket failover (region-a→region-b) verified; "
                "hosted multi-region object DR still open"
                if ok else "MinIO dual-bucket failover assertions failed"
            ),
        })
    except Exception as exc:
        evidence["ok"] = False
        evidence["reason"] = f"MinIO multi-region drill failed: {exc}"
    finally:
        for store in (store_a, store_b):
            try:
                store.delete(key)
            except Exception:
                pass
    if not _write(evidence, ops_dir):
        return _linked_minio()
    return evidence


def _write(evidence: dict, ops_dir: Path | None) -> bool:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "minio_multi_region_drill.json"
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
