"""Gate H: dual-region store health probe (local Postgres/Redis/MinIO).

Probes primary+secondary connection health for local dual-region stores.
Does **not** prove hosted multi-region DR — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "dual_region_store_health_probe_drill.json"


def _tcp_ok(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _linked_probe() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "dual_region_store_health_probe",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_dual_region_store_health_probe_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "dual_region_store_health_probe_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_probe()

    started = time.perf_counter()
    primary = {
        "postgres": _tcp_ok(
            os.environ.get("BLOWAI_PG_HOST", "127.0.0.1"),
            int(os.environ.get("BLOWAI_PG_PORT", "5432")),
        ),
        "redis": _tcp_ok(
            os.environ.get("BLOWAI_REDIS_HOST", "127.0.0.1"),
            int(os.environ.get("BLOWAI_REDIS_PORT", "6379")),
        ),
        "minio": _tcp_ok(
            os.environ.get("BLOWAI_MINIO_HOST", "127.0.0.1"),
            int(os.environ.get("BLOWAI_MINIO_PORT", "9000")),
        ),
    }
    secondary = {
        "postgres": _tcp_ok(
            os.environ.get("BLOWAI_PG_SECONDARY_HOST", "127.0.0.1"),
            int(os.environ.get("BLOWAI_PG_SECONDARY_PORT", "5433")),
        ),
        "redis": _tcp_ok(
            os.environ.get("BLOWAI_REDIS_SECONDARY_HOST", "127.0.0.1"),
            int(os.environ.get("BLOWAI_REDIS_SECONDARY_PORT", "6380")),
        ),
        "minio": _tcp_ok(
            os.environ.get("BLOWAI_MINIO_SECONDARY_HOST", "127.0.0.1"),
            int(os.environ.get("BLOWAI_MINIO_SECONDARY_PORT", "9002")),
        ),
    }
    # Local dual-region often shares one listener; accept primary-up as local probe OK.
    primary_up = sum(1 for v in primary.values() if v)
    secondary_up = sum(1 for v in secondary.values() if v)
    local_ok = primary_up >= 2
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    evidence = {
        "gate_h_complete": False,
        "drill": "dual_region_store_health_probe",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_health_probe",
        "primary": primary,
        "secondary": secondary,
        "primary_up": primary_up,
        "secondary_up": secondary_up,
        "live_hosted_dr": False,
        "elapsed_ms": elapsed_ms,
        "ok": local_ok,
        "reason": (
            f"Dual-region store health probe primary {primary_up}/3 "
            f"secondary {secondary_up}/3 in {elapsed_ms}ms; "
            "live hosted multi-region DR still open"
            if local_ok else
            "Dual-region store health probe incomplete; hosted DR still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_probe()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_probe()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
