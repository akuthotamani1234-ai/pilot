"""Gate G/B: live Redis connectivity + exclusive lease drill via redis-cli.

Does not replace DurableQueue SQLite. Proves Redis is reachable and SETNX leases
exclude a second claimant. Full Redis durable-queue adapter remains open.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "redis_lease_drill.json"


def _url() -> str:
    return (os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL") or "").strip()


def _cli(url: str, *cmd: str) -> subprocess.CompletedProcess:
    args = ["redis-cli"]
    if url.startswith(("redis://", "rediss://")):
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


def lease_drill(*, url: str | None = None) -> dict:
    target = (url or _url() or "redis://127.0.0.1:6379/0").strip()
    evidence: dict = {
        "gate_g_complete": False,
        "gate_b_complete": False,
        "drill": "redis_setnx_lease",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "backend": "redis-cli",
        "ok": False,
        "reason": "",
        "url_host": urlparse(target).hostname if target.startswith("redis") else "local",
    }
    ping = _cli(target, "PING")
    if ping.returncode != 0 or ping.stdout.strip().upper() != "PONG":
        evidence["reason"] = f"redis PING failed: {(ping.stderr or ping.stdout)[:200]}"
        return evidence
    key = f"qpilot:drill:lease:{int(time.time())}"
    first = _cli(target, "SET", key, "worker-a", "NX", "EX", "30")
    second = _cli(target, "SET", key, "worker-b", "NX", "EX", "30")
    owner = _cli(target, "GET", key)
    _cli(target, "DEL", key)
    ok = (
        first.returncode == 0
        and first.stdout.strip() == "OK"
        and second.stdout.strip() in {"", "(nil)"}
        and owner.stdout.strip() == "worker-a"
    )
    evidence.update({
        "ok": ok,
        "first_claim": first.stdout.strip(),
        "second_claim": second.stdout.strip() or "(nil)",
        "owner": owner.stdout.strip(),
        "reason": (
            "Live Redis PING + SETNX exclusive lease verified; DurableQueue Redis adapter still open"
            if ok else
            "Lease exclusivity assertions failed"
        ),
    })
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    art = ROOT / "artifacts" / "ops" / "redis_lease_drill.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
