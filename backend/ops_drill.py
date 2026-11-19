"""Gate H: local offline ops drill helpers.

Produces dated evidence under artifacts/ops/. Never marks Gate H complete —
live observability/DR/load/incident drills remain open.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPS_DIR = ROOT / "artifacts" / "ops"
BACKUP_EVIDENCE = OPS_DIR / "backup_restore_drill.json"
METRICS_EVIDENCE = OPS_DIR / "local_metrics_snapshot.json"


def _ops_folder(ops_dir: Path | None) -> Path | None:
    """This drill's folder. A link is not this install's evidence folder."""
    from .finalization import folder_is_linked
    base = Path(ops_dir) if ops_dir is not None else OPS_DIR
    if folder_is_linked(base):
        return None
    return base


def _linked_drill(kind: str) -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": kind,
        "requests": 0,
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def _write_ops(base: Path, name: str, payload: dict) -> bool:
    from .finalization import write_text_unless_linked
    return write_text_unless_linked(base, name, json.dumps(payload, indent=2))


def run_backup_restore_drill(*, ops_dir: Path | None = None) -> dict:
    """Copy a tiny SQLite DB, restore into an isolated folder, verify rows."""
    base = _ops_folder(ops_dir)
    if base is None:
        return _linked_drill("backup_restore_local_sqlite")
    base.mkdir(parents=True, exist_ok=True)
    src_dir = base / "drill_src"
    bak_dir = base / "drill_backup"
    restore_dir = base / "drill_restore"
    evidence_path = base / "backup_restore_drill.json"
    from .finalization import folder_is_linked
    if any(folder_is_linked(path) for path in (src_dir, bak_dir, restore_dir, evidence_path)):
        return _linked_drill("backup_restore_local_sqlite")
    for d in (src_dir, bak_dir, restore_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    src_db = src_dir / "runs.sqlite"
    with sqlite3.connect(str(src_db)) as conn:
        conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, note TEXT)")
        conn.execute("INSERT INTO runs (id, note) VALUES (?, ?)", ("run-drill", "gate-h-local"))
        conn.commit()

    shutil.copy2(src_db, bak_dir / "runs.sqlite")
    shutil.copy2(bak_dir / "runs.sqlite", restore_dir / "runs.sqlite")

    with sqlite3.connect(str(restore_dir / "runs.sqlite")) as conn:
        row = conn.execute("SELECT id, note FROM runs WHERE id = ?", ("run-drill",)).fetchone()
    ok = bool(row) and row[0] == "run-drill" and row[1] == "gate-h-local"
    evidence = {
        "gate_h_complete": False,
        "drill": "backup_restore_local_sqlite",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ok": ok,
        "source": str(src_db.relative_to(ROOT)) if src_db.is_relative_to(ROOT) else str(src_db),
        "backup": str((bak_dir / "runs.sqlite").relative_to(ROOT))
        if (bak_dir / "runs.sqlite").is_relative_to(ROOT) else str(bak_dir / "runs.sqlite"),
        "restored_row": {"id": row[0], "note": row[1]} if row else None,
        "reason": "Local SQLite backup/restore verified offline; live DR/object-store drills still open",
    }
    if not _write_ops(base, "backup_restore_drill.json", evidence):
        return _linked_drill("backup_restore_local_sqlite")
    return evidence


def write_local_metrics_snapshot(*, ops_dir: Path | None = None) -> dict:
    """Write a process-local metrics snapshot (not a real metrics stack)."""
    base = _ops_folder(ops_dir)
    if base is None:
        return _linked_drill("local_process_snapshot")
    base.mkdir(parents=True, exist_ok=True)
    snap = {
        "gate_h_complete": False,
        "kind": "local_process_snapshot",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metrics": {
            "approvals_db_present": (ROOT / "artifacts" / "approvals.sqlite").is_file(),
            "ops_dir_present": base.is_dir(),
            "ci_workflow_present": (ROOT / ".github" / "workflows" / "blow-ai.yml").is_file(),
        },
        "reason": "Local snapshot only; central metrics/tracing/alerting still open",
    }
    if not _write_ops(base, "local_metrics_snapshot.json", snap):
        return _linked_drill("local_process_snapshot")
    return snap


def run_local_load_probe(*, requests: int = 40, ops_dir: Path | None = None) -> dict:
    """Hit /api/v1/blueprint/progress via TestClient. Not a production soak."""
    from fastapi.testclient import TestClient

    from backend.server import app

    base = _ops_folder(ops_dir)
    if base is None:
        return _linked_drill("local_api_load_probe")
    base.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    headers = {"host": "127.0.0.1"}
    n = max(1, min(500, int(requests)))
    ok = 0
    lat: list[float] = []
    t0 = time.perf_counter()
    for _ in range(n):
        started = time.perf_counter()
        resp = client.get("/api/v1/blueprint/progress", headers=headers)
        lat.append((time.perf_counter() - started) * 1000)
        if resp.status_code == 200 and resp.json().get("complete") is False:
            ok += 1
    elapsed = time.perf_counter() - t0
    lat.sort()
    evidence = {
        "gate_h_complete": False,
        "drill": "local_api_load_probe",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requests": n,
        "ok": ok,
        "elapsed_s": round(elapsed, 3),
        "rps": round(n / elapsed, 2) if elapsed else 0,
        "p50_ms": round(lat[len(lat) // 2], 2) if lat else 0,
        "p95_ms": round(lat[max(0, int(len(lat) * 0.95) - 1)], 2) if lat else 0,
        "reason": "Local TestClient probe only; soak against controlled fixture / prod-like load still open",
    }
    if not _write_ops(base, "local_load_probe.json", evidence):
        return _linked_drill("local_api_load_probe")
    docs = ROOT / "docs" / "ops-evidence"
    if ops_dir is None and _ops_folder(docs):
        docs.mkdir(parents=True, exist_ok=True)
        _write_ops(docs, "local_load_probe.json", evidence)
    return evidence
