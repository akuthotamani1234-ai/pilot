"""QX-A01 durable swarm queue (local-first).

In-process Lease ownership is not enough for Gate B. This module persists tasks,
leases them with heartbeats, recovers expired leases, retries transient failures,
and rejects duplicate irreversible acknowledgments via idempotency keys.

Enterprise Redis/Postgres can replace the SQLite store later behind the same API.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 1
TASK_STATES = frozenset({
    "pending", "leased", "succeeded", "failed", "retry_wait", "blocked", "cancelled",
})
TRANSIENT = frozenset({"network", "worker_crash", "timeout", "lease_expired"})


def _now() -> float:
    return time.time()


def queue_path_is_linked(path: str | Path) -> bool:
    """True when this queue file, or a folder on the way to it, is a link."""
    path = Path(path)
    if path.is_absolute():
        cursor = Path(path.anchor)
        parts = path.parts[1:]
    else:
        cursor = Path()
        parts = path.parts
    for part in parts:
        if not part or part in {".", ".."}:
            return True
        cursor = cursor / part
        if cursor.is_symlink():
            return True
        if not cursor.exists():
            return False
    return False


def lease_is_current(row, worker_id: str, now: float) -> bool:
    """True when ``worker_id`` still holds an unexpired lease."""
    if not row:
        return False
    try:
        status = row["status"]
        owner = row["lease_owner"]
        until = row["lease_until"]
    except (KeyError, IndexError, TypeError):
        return False
    if status != "leased" or owner != worker_id or until is None:
        return False
    try:
        return float(until) >= float(now)
    except (TypeError, ValueError):
        return False


class DurableQueue:
    """SQLite-backed task queue with leases, attempts, and checkpoints."""

    def __init__(self, path: str | Path, *, lease_seconds: int = 90, max_attempts: int = 3) -> None:
        self.path = Path(path)
        if queue_path_is_linked(self.path):
            raise ValueError("The swarm queue is a link.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("The swarm queue is a link.")
        self.lease_seconds = int(lease_seconds)
        self.max_attempts = int(max_attempts)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=2000")
        self._setup()

    def _setup(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              task_id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              role TEXT NOT NULL,
              status TEXT NOT NULL,
              attempt INTEGER NOT NULL DEFAULT 0,
              max_attempts INTEGER NOT NULL,
              lease_owner TEXT,
              lease_until REAL,
              idempotency_key TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              result_json TEXT,
              checkpoint_json TEXT,
              error_class TEXT,
              updated_at REAL NOT NULL,
              UNIQUE(run_id, idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_run_status ON tasks(run_id, status);
            CREATE INDEX IF NOT EXISTS idx_tasks_lease ON tasks(status, lease_until);
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def enqueue(self, *, run_id: str, role: str, payload: dict,
                idempotency_key: str | None = None, max_attempts: int | None = None) -> dict:
        """Insert a pending task. Duplicate idempotency keys return the existing row."""
        key = idempotency_key or uuid4().hex
        existing = self._db.execute(
            "SELECT * FROM tasks WHERE run_id=? AND idempotency_key=?",
            (run_id, key),
        ).fetchone()
        if existing:
            return self._row(existing)
        task_id = uuid4().hex
        now = _now()
        envelope = {
            "task_id": task_id,
            "run_id": run_id,
            "role": role,
            "schema_version": SCHEMA_VERSION,
            "status": "pending",
            "attempt": 0,
            "idempotency_key": key,
            "payload": payload,
        }
        try:
            self._db.execute(
                """INSERT INTO tasks(
                     task_id, run_id, role, status, attempt, max_attempts, idempotency_key,
                     payload_json, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (task_id, run_id, role, "pending", 0, int(max_attempts or self.max_attempts),
                 key, json.dumps(payload), now),
            )
            self._db.commit()
        except sqlite3.IntegrityError:
            self._db.rollback()
            existing = self._db.execute(
                "SELECT * FROM tasks WHERE run_id=? AND idempotency_key=?",
                (run_id, key),
            ).fetchone()
            if existing:
                return self._row(existing)
            raise
        return envelope

    def claim(self, *, worker_id: str, run_id: str | None = None) -> dict | None:
        """Lease the next pending/retry_wait task for worker_id after recovering expired leases."""
        self.recover_expired()
        now = _now()
        if run_id:
            row = self._db.execute(
                """SELECT * FROM tasks
                   WHERE run_id=? AND status IN ('pending','retry_wait')
                     AND (lease_until IS NULL OR lease_until < ?)
                   ORDER BY updated_at ASC LIMIT 1""",
                (run_id, now),
            ).fetchone()
        else:
            row = self._db.execute(
                """SELECT * FROM tasks
                   WHERE status IN ('pending','retry_wait')
                     AND (lease_until IS NULL OR lease_until < ?)
                   ORDER BY updated_at ASC LIMIT 1""",
                (now,),
            ).fetchone()
        if not row:
            return None
        attempt = int(row["attempt"]) + 1
        until = now + self.lease_seconds
        cur = self._db.execute(
            """UPDATE tasks SET status='leased', attempt=?, lease_owner=?, lease_until=?, updated_at=?
               WHERE task_id=? AND status IN ('pending','retry_wait')""",
            (attempt, worker_id, until, now, row["task_id"]),
        )
        self._db.commit()
        if cur.rowcount != 1:
            return self.claim(worker_id=worker_id, run_id=run_id)
        return self.get(row["task_id"])

    def heartbeat(self, task_id: str, worker_id: str) -> bool:
        """Extend the lease. Returns False if this worker no longer owns it."""
        now = _now()
        until = now + self.lease_seconds
        cur = self._db.execute(
            """UPDATE tasks SET lease_until=?, updated_at=?
               WHERE task_id=? AND lease_owner=? AND status='leased' AND lease_until >= ?""",
            (until, now, task_id, worker_id, now),
        )
        self._db.commit()
        return cur.rowcount == 1

    def checkpoint(self, task_id: str, worker_id: str, checkpoint: dict) -> bool:
        """Persist resume state while the lease is held."""
        now = _now()
        cur = self._db.execute(
            """UPDATE tasks SET checkpoint_json=?, updated_at=?
               WHERE task_id=? AND lease_owner=? AND status='leased' AND lease_until >= ?""",
            (json.dumps(checkpoint), now, task_id, worker_id, now),
        )
        self._db.commit()
        return cur.rowcount == 1

    def complete(self, task_id: str, worker_id: str, result: dict) -> tuple[bool, str]:
        """Ack success once. An expired lease cannot ack."""
        row = self._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return False, "missing task"
        if row["status"] == "succeeded":
            return True, "already succeeded"
        now = _now()
        cur = self._db.execute(
            """UPDATE tasks SET status='succeeded', result_json=?, lease_owner=NULL, lease_until=NULL,
                   error_class=NULL, updated_at=?
               WHERE task_id=? AND lease_owner=? AND status='leased' AND lease_until >= ?""",
            (json.dumps(result), now, task_id, worker_id, now),
        )
        self._db.commit()
        if cur.rowcount != 1:
            return False, "worker does not own this lease"
        return True, ""

    def fail(self, task_id: str, worker_id: str, *, error_class: str, detail: str = "") -> tuple[bool, str]:
        """Classify failure. Transient errors retry until max_attempts; others fail closed."""
        row = self._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return False, "missing task"
        now = _now()
        if not lease_is_current(row, worker_id, now):
            return False, "worker does not own this lease"
        attempt = int(row["attempt"])
        max_attempts = int(row["max_attempts"])
        transient = error_class in TRANSIENT
        if transient and attempt < max_attempts:
            status = "retry_wait"
            msg = "scheduled retry"
        else:
            status = "failed"
            msg = "permanent failure" if not transient else "attempts exhausted"
        result = {"error_class": error_class, "detail": detail, "attempt": attempt}
        cur = self._db.execute(
            """UPDATE tasks SET status=?, result_json=?, error_class=?, lease_owner=NULL, lease_until=NULL,
                   updated_at=?
               WHERE task_id=? AND lease_owner=? AND status='leased' AND lease_until >= ?""",
            (status, json.dumps(result), error_class, now, task_id, worker_id, now),
        )
        self._db.commit()
        if cur.rowcount != 1:
            return False, "worker does not own this lease"
        return True, msg

    def mark_blocked(self, task_id: str, reason: str = "") -> bool:
        now = _now()
        cur = self._db.execute(
            """UPDATE tasks SET status='blocked', error_class=?, lease_owner=NULL, lease_until=NULL, updated_at=?
               WHERE task_id=? AND status IN ('pending','retry_wait')""",
            (reason or "blocked", now, task_id),
        )
        self._db.commit()
        return cur.rowcount == 1

    def cancel(self, task_id: str) -> bool:
        now = _now()
        cur = self._db.execute(
            """UPDATE tasks SET status='cancelled', lease_owner=NULL, lease_until=NULL, updated_at=?
               WHERE task_id=? AND status IN ('pending','leased','retry_wait','blocked')""",
            (now, task_id),
        )
        self._db.commit()
        return cur.rowcount == 1

    def recover_expired(self) -> list[str]:
        """Requeue leased tasks whose heartbeat expired (worker crash / lost lease)."""
        now = _now()
        rows = self._db.execute(
            "SELECT task_id, attempt, max_attempts FROM tasks WHERE status='leased' AND lease_until < ?",
            (now,),
        ).fetchall()
        recovered = []
        for row in rows:
            if int(row["attempt"]) < int(row["max_attempts"]):
                status = "retry_wait"
            else:
                status = "failed"
            cur = self._db.execute(
                """UPDATE tasks SET status=?, lease_owner=NULL, lease_until=NULL,
                       error_class='lease_expired', updated_at=?
                   WHERE task_id=? AND status='leased' AND lease_until < ?""",
                (status, now, row["task_id"], now),
            )
            if cur.rowcount == 1:
                recovered.append(row["task_id"])
        if recovered:
            self._db.commit()
        return recovered

    def get(self, task_id: str) -> dict | None:
        row = self._db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        return self._row(row) if row else None

    def list_run(self, run_id: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM tasks WHERE run_id=? ORDER BY updated_at ASC",
            (run_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def _row(self, row: sqlite3.Row) -> dict:
        payload = json.loads(row["payload_json"])
        result = json.loads(row["result_json"]) if row["result_json"] else None
        checkpoint = json.loads(row["checkpoint_json"]) if row["checkpoint_json"] else None
        return {
            "task_id": row["task_id"],
            "run_id": row["run_id"],
            "role": row["role"],
            "schema_version": SCHEMA_VERSION,
            "status": row["status"],
            "attempt": int(row["attempt"]),
            "max_attempts": int(row["max_attempts"]),
            "lease_owner": row["lease_owner"],
            "lease_until": row["lease_until"],
            "idempotency_key": row["idempotency_key"],
            "payload": payload,
            "result": result,
            "checkpoint": checkpoint,
            "error_class": row["error_class"],
            "updated_at": row["updated_at"],
        }
