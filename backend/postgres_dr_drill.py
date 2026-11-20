"""Gate H: Postgres dump → restore into an isolated database.

Uses local ``pg_dump`` / ``psql`` against ``POSTGRES_URL``. Hosted multi-region
DR / on-call still open — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "postgres_dr_drill.json"
ISOLATED_DB = "qpilot_dr_restore"


def _dsn() -> str:
    return (os.getenv("POSTGRES_URL") or os.getenv("QPILOT_DB_URL") or "").strip()


def _admin_dsn(dsn: str) -> str:
    """Point DSN at the maintenance DB so we can CREATE/DROP the isolated DB."""
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path="/postgres"))


def _isolated_dsn(dsn: str, db_name: str) -> str:
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path="/" + db_name))


def _linked_pg_dr() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "postgres_dump_restore_isolated",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_postgres_dr_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "postgres_dr_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_pg_dr()

    dsn = _dsn()
    if not dsn:
        evidence = {
            "gate_h_complete": False,
            "drill": "postgres_dump_restore_isolated",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "reason": "POSTGRES_URL not set — cannot run Postgres DR drill",
        }
    else:
        dump_dir = ROOT / "artifacts" / "ops" / "postgres_dr"
        dump_path = dump_dir / "qpilot.dump.sql"
        if folder_is_linked(dump_dir) or folder_is_linked(dump_path):
            return _linked_pg_dr()
        dump_dir.mkdir(parents=True, exist_ok=True)
        admin = _admin_dsn(dsn)
        isolated = _isolated_dsn(dsn, ISOLATED_DB)
        steps: list[dict] = []
        ok = False
        reason = ""
        try:
            if folder_is_linked(dump_dir) or folder_is_linked(dump_path):
                return _linked_pg_dr()
            dump = subprocess.run(
                ["pg_dump", "--no-owner", "--no-acl", "-f", str(dump_path), dsn],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            steps.append({"step": "pg_dump", "rc": dump.returncode})
            if dump.returncode != 0:
                raise RuntimeError((dump.stderr or dump.stdout or "pg_dump failed")[:300])

            # Drop/create isolated DB via admin connection (fixed identifier only).
            if not ISOLATED_DB.isidentifier():
                raise RuntimeError("isolated DB name is not a safe identifier")
            term = subprocess.run(
                [
                    "psql", admin, "-v", "ON_ERROR_STOP=1",
                    "-v", f"db={ISOLATED_DB}",
                    "-c",
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :'db' AND pid <> pg_backend_pid();",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            steps.append({"step": "terminate", "rc": term.returncode})
            for label, sql in (
                ("DROP", f"DROP DATABASE IF EXISTS {ISOLATED_DB}"),
                ("CREATE", f"CREATE DATABASE {ISOLATED_DB}"),
            ):
                proc = subprocess.run(
                    ["psql", admin, "-v", "ON_ERROR_STOP=1", "-c", sql],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
                steps.append({"step": label, "rc": proc.returncode})
                if proc.returncode != 0:
                    raise RuntimeError((proc.stderr or proc.stdout or "psql failed")[:300])

            restore = subprocess.run(
                ["psql", isolated, "-v", "ON_ERROR_STOP=1", "-f", str(dump_path)],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            steps.append({"step": "psql_restore", "rc": restore.returncode})
            if restore.returncode != 0:
                raise RuntimeError((restore.stderr or restore.stdout or "restore failed")[:300])

            verify = subprocess.run(
                ["psql", isolated, "-tAc", "SELECT count(*) FROM information_schema.tables "
                 "WHERE table_schema NOT IN ('pg_catalog','information_schema');"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            table_count = int((verify.stdout or "0").strip() or "0")
            steps.append({"step": "verify_tables", "rc": verify.returncode, "tables": table_count})
            ok = verify.returncode == 0 and table_count >= 0
            reason = (
                f"Postgres dump restored into isolated DB {ISOLATED_DB} "
                f"({table_count} user tables); hosted multi-region DR / on-call still open"
            )
        except (OSError, ValueError, subprocess.TimeoutExpired, RuntimeError) as exc:
            ok = False
            reason = f"Postgres DR drill failed: {exc}; hosted DR still open"
            steps.append({"step": "error", "detail": str(exc)[:300]})

        evidence = {
            "gate_h_complete": False,
            "drill": "postgres_dump_restore_isolated",
            "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": ok,
            "isolated_db": ISOLATED_DB,
            "dump_bytes": dump_path.stat().st_size if dump_path.is_file() else 0,
            "steps": steps,
            "reason": reason,
        }

    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_pg_dr()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_pg_dr()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
