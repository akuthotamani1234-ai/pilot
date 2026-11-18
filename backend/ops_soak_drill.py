"""Gate H: controlled soak against the owned AdminPortal fixture.

Repeated HTTP GETs for a bounded window. Not hosted/prod-like load — Gate H
stays incomplete.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
OPS_DIR = ROOT / "artifacts" / "ops"
PATHS = ("/", "/users", "/users/new", "/widgets", "/reports", "/help")


def _http_get(url: str) -> int:
    """GET ``url`` (http/https only) and return the status code."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    req = urllib.request.Request(url, method="GET")  # noqa: S310
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        resp.read(64)
        return int(getattr(resp, "status", 200) or 200)


def run_controlled_soak(
    *,
    duration_s: float = 20.0,
    ops_dir: Path | None = None,
    base_url: str | None = None,
) -> dict:
    """Soak a local AdminPortal (or ``base_url``) for ``duration_s`` seconds."""
    base = Path(ops_dir) if ops_dir else OPS_DIR
    base.mkdir(parents=True, exist_ok=True)
    portal = None
    url = (base_url or "").rstrip("/")
    started_portal = False
    if not url:
        from tests.admin_portal import AdminPortal

        portal = AdminPortal(0, bugs=False).start()
        url = portal.url.rstrip("/")
        started_portal = True

    ok = 0
    fail = 0
    lat: list[float] = []
    statuses: dict[str, int] = {}
    t0 = time.perf_counter()
    deadline = t0 + max(5.0, min(120.0, float(duration_s)))
    try:
        while time.perf_counter() < deadline:
            for path in PATHS:
                started = time.perf_counter()
                try:
                    code = _http_get(url + path)
                except urllib.error.HTTPError as exc:
                    code = int(exc.code)
                except Exception:
                    fail += 1
                    continue
                lat.append((time.perf_counter() - started) * 1000)
                statuses[str(code)] = statuses.get(str(code), 0) + 1
                if 200 <= code < 400:
                    ok += 1
                else:
                    fail += 1
                if time.perf_counter() >= deadline:
                    break
    finally:
        if started_portal and portal is not None:
            try:
                portal.stop()
            except Exception:
                pass

    elapsed = time.perf_counter() - t0
    lat.sort()
    total = ok + fail
    evidence = {
        "gate_h_complete": False,
        "drill": "controlled_fixture_soak",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "AdminPortal" if started_portal else url,
        "base_url": url if not started_portal else "(ephemeral AdminPortal)",
        "duration_s_target": max(5.0, min(120.0, float(duration_s))),
        "elapsed_s": round(elapsed, 3),
        "requests": total,
        "ok": ok,
        "fail": fail,
        "rps": round(total / elapsed, 2) if elapsed else 0,
        "p50_ms": round(lat[len(lat) // 2], 2) if lat else 0,
        "p95_ms": round(lat[max(0, int(len(lat) * 0.95) - 1)], 2) if lat else 0,
        "status_counts": statuses,
        "paths": list(PATHS),
        "reason": (
            "Controlled AdminPortal soak verified locally; hosted/prod-like load + on-call still open"
        ),
    }
    out = base / "controlled_soak_drill.json"
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        docs = ROOT / "docs" / "ops-evidence"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "controlled_soak_drill.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
