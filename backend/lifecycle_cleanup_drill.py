"""Gate C: offline lifecycle cleanup confirmation drill.

Exercises durable Lifecycle + created.jsonl remote_delete adapter without a
live portal. Gate C stays incomplete (broader live portal paths still open).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .data_lifecycle import (
    Lifecycle,
    created_jsonl_delete,
    ingest_created,
    save_lifecycle,
    to_state,
)

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "lifecycle_cleanup_drill.json"


def run_lifecycle_cleanup_drill(*, ops_dir: Path | None = None, work_dir: Path | None = None) -> dict:
    base = Path(work_dir) if work_dir else (ROOT / "artifacts" / "ops" / "lifecycle_cleanup_work")
    base.mkdir(parents=True, exist_ok=True)
    run_dir = base / f"run_{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)

    life = Lifecycle(run_id=run_dir.name, environment="test")
    prepared = life.prepare(1)

    # Staging-created fixture: ingest while still "created", then prove deleted.
    created_path = run_dir / "created.jsonl"
    created_path.write_text(
        json.dumps({"tag": "order:99", "status": "created", "id": "99"}) + "\n",
        encoding="utf-8",
    )
    ingested = ingest_created(life, run_dir)
    with created_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"tag": "order:99", "status": "deleted", "id": "99"}) + "\n")
    save_lifecycle(run_dir, life)

    cleanup = life.cleanup_confirmed(remote_delete=created_jsonl_delete(run_dir))
    save_lifecycle(run_dir, life)

    confirmed_n = len(cleanup.get("confirmed") or [])
    failed_n = len(cleanup.get("failed") or [])
    evidence = {
        "gate_c_complete": False,
        "drill": "offline_lifecycle_cleanup",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prepared_tags": [row.get("tag") for row in prepared],
        "ingested_tags": [row.get("tag") for row in ingested],
        "confirmed": confirmed_n,
        "failed": failed_n,
        "complete": bool(cleanup.get("complete")),
        "local_only": bool(cleanup.get("local_only")),
        "sample_proofs": [
            row.get("cleanup_proof") for row in (cleanup.get("confirmed") or [])[:5]
        ],
        "ok": confirmed_n > 0 and failed_n == 0 and bool(cleanup.get("complete")),
        "state_run_id": to_state(life).get("run_id"),
        "reason": (
            "Offline created.jsonl cleanup confirmation exercised; live AdminPortal / "
            "broader portal cleanup paths still open"
        ),
    }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "lifecycle_cleanup_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "lifecycle_cleanup_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
