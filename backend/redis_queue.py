"""Redis-backed DurableQueue adapter (Gate B/G).

Same behavioral surface as ``swarm_queue.DurableQueue``. Requires the optional
``redis`` package. Gate B/G stay incomplete until product-wide wiring + review.
"""
from __future__ import annotations

import json
import time
from urllib.parse import urlparse
from uuid import uuid4

from .redis_queue_scripts import (
    CLAIM_WAITING,
    ENQUEUE_ONCE,
    HOLD_LEASE,
    RECOVER_LEASE,
    SET_TERMINAL,
)
from .swarm_queue import SCHEMA_VERSION, TRANSIENT

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None


def _now() -> float:
    return time.time()


class RedisDurableQueue:
    """Redis hash + ZSET queue with leases, retries, and idempotency keys."""

    def __init__(self, url: str, *, lease_seconds: int = 90, max_attempts: int = 3,
                 key_prefix: str = "qpilot:swarm") -> None:
        if redis_lib is None:
            raise RuntimeError("redis package is not installed")
        self.url = url
        self.lease_seconds = int(lease_seconds)
        self.max_attempts = int(max_attempts)
        self.prefix = key_prefix.rstrip(":")
        self._r = redis_lib.Redis.from_url(url, decode_responses=True)
        self._r.ping()

    def close(self) -> None:
        try:
            self._r.close()
        except Exception:
            pass

    def _task_key(self, task_id: str) -> str:
        return f"{self.prefix}:task:{task_id}"

    def _pending_key(self, run_id: str) -> str:
        return f"{self.prefix}:pending:{run_id}"

    def _idem_key(self, run_id: str, key: str) -> str:
        return f"{self.prefix}:idem:{run_id}:{key}"

    def _run_index(self, run_id: str) -> str:
        return f"{self.prefix}:run:{run_id}"

    def _dump(self, task: dict) -> None:
        self._r.hset(self._task_key(task["task_id"]), mapping={
            "task_id": task["task_id"],
            "run_id": task["run_id"],
            "role": task["role"],
            "status": task["status"],
            "attempt": str(task["attempt"]),
            "max_attempts": str(task["max_attempts"]),
            "lease_owner": task.get("lease_owner") or "",
            "lease_until": "" if task.get("lease_until") is None else str(task["lease_until"]),
            "idempotency_key": task["idempotency_key"],
            "payload_json": json.dumps(task.get("payload") or {}),
            "result_json": "" if task.get("result") is None else json.dumps(task["result"]),
            "checkpoint_json": "" if task.get("checkpoint") is None else json.dumps(task["checkpoint"]),
            "error_class": task.get("error_class") or "",
            "updated_at": str(task.get("updated_at") or _now()),
        })
        self._r.sadd(self._run_index(task["run_id"]), task["task_id"])

    def _load(self, task_id: str) -> dict | None:
        raw = self._r.hgetall(self._task_key(task_id))
        if not raw:
            return None
        lease_until = raw.get("lease_until") or ""
        return {
            "task_id": raw["task_id"],
            "run_id": raw["run_id"],
            "role": raw["role"],
            "schema_version": SCHEMA_VERSION,
            "status": raw["status"],
            "attempt": int(raw.get("attempt") or 0),
            "max_attempts": int(raw.get("max_attempts") or self.max_attempts),
            "lease_owner": raw.get("lease_owner") or None,
            "lease_until": float(lease_until) if lease_until else None,
            "idempotency_key": raw["idempotency_key"],
            "payload": json.loads(raw.get("payload_json") or "{}"),
            "result": json.loads(raw["result_json"]) if raw.get("result_json") else None,
            "checkpoint": json.loads(raw["checkpoint_json"]) if raw.get("checkpoint_json") else None,
            "error_class": raw.get("error_class") or None,
            "updated_at": float(raw.get("updated_at") or 0),
        }

    def _held_update(
        self, task_id: str, worker_id: str, mapping: dict, *, pending_key: str = "",
    ) -> bool:
        """Write ``mapping`` only if ``worker_id`` still holds an unexpired lease."""
        script = getattr(self, "_hold_script", None)
        if script is None:
            script = self._r.register_script(HOLD_LEASE)
            self._hold_script = script
        now = _now()
        args = [worker_id, str(now), task_id, "1" if pending_key else "0"]
        for key, value in mapping.items():
            args.append(key)
            args.append("" if value is None else str(value))
        pending = pending_key or self._task_key(task_id)
        result = script(keys=[self._task_key(task_id), pending], args=args)
        return int(result) == 1

    def enqueue(self, *, run_id: str, role: str, payload: dict,
                idempotency_key: str | None = None, max_attempts: int | None = None) -> dict:
        key = idempotency_key or uuid4().hex
        task_id = uuid4().hex
        now = _now()
        task = {
            "task_id": task_id,
            "run_id": run_id,
            "role": role,
            "schema_version": SCHEMA_VERSION,
            "status": "pending",
            "attempt": 0,
            "max_attempts": int(max_attempts or self.max_attempts),
            "lease_owner": None,
            "lease_until": None,
            "idempotency_key": key,
            "payload": payload,
            "result": None,
            "checkpoint": None,
            "error_class": None,
            "updated_at": now,
        }
        mapping = {
            "task_id": task_id,
            "run_id": run_id,
            "role": role,
            "status": "pending",
            "attempt": "0",
            "max_attempts": str(task["max_attempts"]),
            "lease_owner": "",
            "lease_until": "",
            "idempotency_key": key,
            "payload_json": json.dumps(payload),
            "result_json": "",
            "checkpoint_json": "",
            "error_class": "",
            "updated_at": str(now),
        }
        args = [task_id, str(now)]
        for field, value in mapping.items():
            args.extend((field, value))
        stored = self._lua("enqueue", ENQUEUE_ONCE)(
            keys=[
                self._idem_key(run_id, key),
                self._task_key(task_id),
                self._pending_key(run_id),
                self._run_index(run_id),
            ],
            args=args,
        )
        if str(stored) != task_id:
            existing = self._load(str(stored))
            if existing:
                return existing
        return task

    def _lua(self, name: str, source: str):
        cache = getattr(self, "_lua_cache", None)
        if cache is None:
            cache = {}
            self._lua_cache = cache
        script = cache.get(name)
        if script is None:
            script = self._r.register_script(source)
            cache[name] = script
        return script

    def _recover_script(self):
        script = getattr(self, "_recover_lease", None)
        if script is None:
            script = self._r.register_script(RECOVER_LEASE)
            self._recover_lease = script
        return script

    def recover_expired(self) -> list[str]:
        recovered = []
        script = self._recover_script()
        for key in self._r.scan_iter(match=f"{self.prefix}:run:*"):
            run_id = key.rsplit(":", 1)[-1]
            for task_id in self._r.smembers(key):
                row = self._load(task_id)
                if not row or row["status"] != "leased":
                    continue
                if row.get("lease_until") is not None and row["lease_until"] >= _now():
                    continue
                status = "retry_wait" if row["attempt"] < row["max_attempts"] else "failed"
                now = _now()
                result = script(
                    keys=[self._task_key(task_id), self._pending_key(run_id)],
                    args=[str(now), status, task_id],
                )
                if int(result) == 1:
                    recovered.append(task_id)
        return recovered

    def claim(self, *, worker_id: str, run_id: str | None = None) -> dict | None:
        self.recover_expired()
        if not run_id:
            # Claim across first pending key found
            keys = list(self._r.scan_iter(match=f"{self.prefix}:pending:*", count=10))
            if not keys:
                return None
            run_id = keys[0].rsplit(":", 1)[-1]
        pending = self._pending_key(run_id)
        while True:
            item = self._r.zpopmin(pending, count=1)
            if not item:
                return None
            task_id = item[0][0]
            row = self._load(task_id)
            if not row or row["status"] not in {"pending", "retry_wait"}:
                continue
            now = _now()
            attempt = int(row["attempt"]) + 1
            until = now + self.lease_seconds
            ok = self._lua("claim", CLAIM_WAITING)(
                keys=[self._task_key(task_id)],
                args=[str(now), str(attempt), worker_id, str(until)],
            )
            if int(ok) != 1:
                continue
            return self._load(task_id) or row

    def heartbeat(self, task_id: str, worker_id: str) -> bool:
        now = _now()
        return self._held_update(task_id, worker_id, {
            "lease_until": str(now + self.lease_seconds),
            "updated_at": str(now),
        })

    def checkpoint(self, task_id: str, worker_id: str, checkpoint: dict) -> bool:
        return self._held_update(task_id, worker_id, {
            "checkpoint_json": json.dumps(checkpoint),
            "updated_at": str(_now()),
        })

    def complete(self, task_id: str, worker_id: str, result: dict) -> tuple[bool, str]:
        row = self._load(task_id)
        if not row:
            return False, "missing task"
        if row["status"] == "succeeded":
            return True, "already succeeded"
        now = _now()
        ok = self._held_update(task_id, worker_id, {
            "status": "succeeded",
            "result_json": json.dumps(result),
            "lease_owner": "",
            "lease_until": "",
            "error_class": "",
            "updated_at": str(now),
        })
        if not ok:
            return False, "worker does not own this lease"
        return True, ""

    def fail(self, task_id: str, worker_id: str, *, error_class: str, detail: str = "") -> tuple[bool, str]:
        row = self._load(task_id)
        if not row:
            return False, "missing task"
        attempt = int(row["attempt"])
        transient = error_class in TRANSIENT
        if transient and attempt < int(row["max_attempts"]):
            status = "retry_wait"
            msg = "scheduled retry"
        else:
            status = "failed"
            msg = "permanent failure" if not transient else "attempts exhausted"
        now = _now()
        pending = self._pending_key(row["run_id"]) if status == "retry_wait" else ""
        ok = self._held_update(
            task_id, worker_id,
            {
                "status": status,
                "result_json": json.dumps({
                    "error_class": error_class, "detail": detail, "attempt": attempt,
                }),
                "error_class": error_class,
                "lease_owner": "",
                "lease_until": "",
                "updated_at": str(now),
            },
            pending_key=pending,
        )
        if not ok:
            return False, "worker does not own this lease"
        return True, msg

    def _terminal(self, task_id: str, status: str, error_class: str, allowed: tuple[str, ...]) -> bool:
        row = self._load(task_id)
        if not row or row["status"] not in allowed:
            return False
        now = _now()
        result = self._lua("terminal", SET_TERMINAL)(
            keys=[self._task_key(task_id), self._pending_key(row["run_id"])],
            args=[str(now), status, error_class, task_id, *allowed],
        )
        return int(result) == 1

    def mark_blocked(self, task_id: str, reason: str = "") -> bool:
        return self._terminal(task_id, "blocked", reason or "blocked", ("pending", "retry_wait"))

    def cancel(self, task_id: str) -> bool:
        row = self._load(task_id)
        kept = "" if not row else str(row.get("error_class") or "")
        return self._terminal(
            task_id, "cancelled", kept, ("pending", "leased", "retry_wait", "blocked"),
        )

    def get(self, task_id: str) -> dict | None:
        return self._load(task_id)

    def list_run(self, run_id: str) -> list[dict]:
        ids = list(self._r.smembers(self._run_index(run_id)))
        rows = [self._load(i) for i in ids]
        return sorted([r for r in rows if r], key=lambda r: r.get("updated_at") or 0)


def redis_host(url: str) -> str:
    return urlparse(url).hostname or "redis"
