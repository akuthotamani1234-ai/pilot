"""Gate H/B: Redis dual-DB (region-a / region-b) failover rehearsal.

Writes a marker into Redis DB 0, copies it to DB 1, deletes DB 0, and reads
from DB 1 as failover. Local multi-DB rehearsal only — hosted Redis
multi-region / sentinel still open; ``gate_h_complete`` / ``gate_b_complete``
stay False.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "redis_multi_region_drill.json"
MARKER = "qpilot-redis-multi-region-v1"


def _base_url() -> str:
    return (os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL") or "redis://127.0.0.1:6379/0").strip()


def _db_url(url: str, db: int) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{db}"))


def _cli(url: str, *cmd: str) -> subprocess.CompletedProcess:
    args = ["redis-cli"]
    parsed = urlparse(url)
    if parsed.hostname:
        args += ["-h", parsed.hostname]
    if parsed.port:
        args += ["-p", str(parsed.port)]
    if parsed.password:
        args += ["-a", parsed.password]
    if parsed.path and parsed.path not in ("", "/"):
        db = parsed.path.lstrip("/")
        if db.isdigit():
            args += ["-n", db]
    args.extend(cmd)
    return subprocess.run(args, capture_output=True, text=True, check=False, timeout=30)


def _linked_redis() -> dict:
    return {
        "gate_h_complete": False,
        "gate_b_complete": False,
        "ok": False,
        "drill": "redis_dual_db_failover",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_redis_multi_region_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "redis_multi_region_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_redis()

    base = _base_url()
    region_a = _db_url(base, 0)
    region_b = _db_url(base, 1)
    key = f"qpilot:drill:mr:{int(time.time())}"
    steps: list[dict] = []
    ran_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        ping_a = _cli(region_a, "PING")
        ping_b = _cli(region_b, "PING")
        steps.append({"step": "ping_a", "ok": ping_a.stdout.strip().upper() == "PONG"})
        steps.append({"step": "ping_b", "ok": ping_b.stdout.strip().upper() == "PONG"})
        if not (steps[0]["ok"] and steps[1]["ok"]):
            raise RuntimeError("Redis PING failed on region-a or region-b")

        set_a = _cli(region_a, "SET", key, MARKER)
        steps.append({"step": "set_region_a", "ok": set_a.stdout.strip() == "OK"})
        get_a = _cli(region_a, "GET", key)
        val = get_a.stdout.strip()
        steps.append({"step": "get_region_a", "ok": val == MARKER, "value": val[:40]})

        # Replicate A → B
        set_b = _cli(region_b, "SET", key, val)
        steps.append({"step": "replicate_to_b", "ok": set_b.stdout.strip() == "OK"})
        _cli(region_a, "DEL", key)
        missing = _cli(region_a, "GET", key)
        primary_gone = missing.stdout.strip() in {"", "(nil)"}
        steps.append({"step": "delete_region_a", "ok": primary_gone})

        failover = _cli(region_b, "GET", key)
        got = failover.stdout.strip()
        steps.append({"step": "failover_read_b", "ok": got == MARKER, "value": got[:40]})
        ok = all(s.get("ok") for s in steps)
        reason = (
            "Local Redis dual-DB failover (db0→db1) verified; "
            "hosted Redis multi-region / sentinel still open"
            if ok else
            "Redis dual-DB failover assertions failed; hosted multi-region still open"
        )
    except Exception as exc:
        ok = False
        reason = f"Redis multi-region drill failed: {exc}; hosted multi-region still open"
        steps.append({"step": "error", "detail": str(exc)[:240]})
    finally:
        _cli(region_a, "DEL", key)
        _cli(region_b, "DEL", key)

    evidence = {
        "gate_h_complete": False,
        "gate_b_complete": False,
        "drill": "redis_dual_db_failover",
        "ran_at": ran_at,
        "ok": ok,
        "region_a_db": 0,
        "region_b_db": 1,
        "key": key,
        "steps": steps,
        "reason": reason,
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_redis()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_redis()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
