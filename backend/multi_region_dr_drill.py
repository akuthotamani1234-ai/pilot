"""Gate H: dual-region Postgres failover rehearsal (local).

Seeds ``qpilot_region_a``, dumps it, restores into ``qpilot_region_b``, and
verifies the marker row is readable after failover. This is a **local**
multi-DB rehearsal — hosted multi-region DR / on-call still open;
``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "multi_region_dr_drill.json"
REGION_A = "qpilot_region_a"
REGION_B = "qpilot_region_b"
MARKER = "qpilot-multi-region-marker-v1"


def _dsn() -> str:
    return (os.getenv("POSTGRES_URL") or os.getenv("QPILOT_DB_URL") or "").strip()


def _admin_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path="/postgres"))


def _db_dsn(dsn: str, db_name: str) -> str:
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path="/" + db_name))


def _psql(dsn: str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["psql", dsn, "-v", "ON_ERROR_STOP=1", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _recreate_db(admin: str, name: str, steps: list[dict]) -> None:
    if not name.isidentifier():
        raise RuntimeError(f"unsafe db name: {name}")
    term = _psql(
        admin,
        "-v", f"db={name}",
        "-c",
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = :'db' AND pid <> pg_backend_pid();",
    )
    steps.append({"step": f"terminate:{name}", "rc": term.returncode})
    for label, sql in (
        ("DROP", f"DROP DATABASE IF EXISTS {name}"),
        ("CREATE", f"CREATE DATABASE {name}"),
    ):
        proc = _psql(admin, "-c", sql)
        steps.append({"step": f"{label}:{name}", "rc": proc.returncode})
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"{label} failed")[:300])


def run_multi_region_dr_drill(*, ops_dir: Path | None = None) -> dict:
    dsn = _dsn()
    ran_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not dsn:
        evidence = {
            "gate_h_complete": False,
            "drill": "multi_region_postgres_failover",
            "ran_at": ran_at,
            "ok": False,
            "reason": "POSTGRES_URL not set — cannot run multi-region DR rehearsal",
        }
    else:
        dump_dir = ROOT / "artifacts" / "ops" / "multi_region_dr"
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump_path = dump_dir / "region_a.dump.sql"
        admin = _admin_dsn(dsn)
        region_a = _db_dsn(dsn, REGION_A)
        region_b = _db_dsn(dsn, REGION_B)
        steps: list[dict] = []
        ok = False
        reason = ""
        try:
            _recreate_db(admin, REGION_A, steps)
            # Fixed identifier + constant marker only (no user input).
            seed_sql = (
                "CREATE TABLE IF NOT EXISTS region_marker ("
                "id int PRIMARY KEY, region text NOT NULL, marker text NOT NULL);"
                "INSERT INTO region_marker(id, region, marker) VALUES "
                "(1, 'region_a', 'qpilot-multi-region-marker-v1') "
                "ON CONFLICT (id) DO UPDATE SET marker = EXCLUDED.marker;"
            )
            seed = _psql(region_a, "-c", seed_sql)
            steps.append({"step": "seed_region_a", "rc": seed.returncode})
            if seed.returncode != 0:
                raise RuntimeError((seed.stderr or seed.stdout or "seed failed")[:300])

            dump = subprocess.run(
                ["pg_dump", "--no-owner", "--no-acl", "-f", str(dump_path), region_a],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            steps.append({"step": "pg_dump_region_a", "rc": dump.returncode})
            if dump.returncode != 0:
                raise RuntimeError((dump.stderr or dump.stdout or "pg_dump failed")[:300])

            _recreate_db(admin, REGION_B, steps)
            restore = _psql(region_b, "-f", str(dump_path), timeout=180)
            steps.append({"step": "restore_region_b", "rc": restore.returncode})
            if restore.returncode != 0:
                raise RuntimeError((restore.stderr or restore.stdout or "restore failed")[:300])

            verify = _psql(
                region_b,
                "-tAc",
                "SELECT marker FROM region_marker WHERE id = 1;",
            )
            marker = (verify.stdout or "").strip()
            steps.append({
                "step": "failover_read_region_b",
                "rc": verify.returncode,
                "marker": marker[:80],
            })
            ok = verify.returncode == 0 and marker == MARKER
            reason = (
                "Local dual-region Postgres failover rehearsal ok "
                f"({REGION_A}→{REGION_B}); hosted multi-region DR / on-call still open"
                if ok else
                f"Multi-region DR rehearsal failed (marker={marker!r}); "
                "hosted multi-region DR still open"
            )
        except Exception as exc:
            # Include FileNotFoundError when psql/pg_dump is absent (e.g. Windows CI).
            ok = False
            reason = f"Multi-region DR rehearsal failed: {exc}; hosted DR still open"
            steps.append({"step": "error", "detail": str(exc)[:300]})

        evidence = {
            "gate_h_complete": False,
            "drill": "multi_region_postgres_failover",
            "ran_at": ran_at,
            "ok": ok,
            "region_a": REGION_A,
            "region_b": REGION_B,
            "dump_bytes": dump_path.stat().st_size if dump_path.is_file() else 0,
            "steps": steps,
            "reason": reason,
        }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "multi_region_dr_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "multi_region_dr_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
