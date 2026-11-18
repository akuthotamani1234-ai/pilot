"""Durable queue backend selector (Gate B / G).

Local SQLite remains the default. A Redis URL is recognized but not silently
treated as ready until a Redis adapter is wired and verified.
"""
from __future__ import annotations

import os
from pathlib import Path

from .swarm_queue import DurableQueue


def open_durable_queue(uri: str | None = None, *, default_path: str | Path = "runs/.swarm_queue.sqlite",
                       lease_seconds: int = 90, max_attempts: int = 3) -> dict:
    """Open a durable queue or explain why the configured backend is unready."""
    raw = (uri if uri is not None else os.getenv("REDIS_URL") or os.getenv("QPILOT_REDIS_URL") or "").strip()
    if not raw or raw.startswith("sqlite:") or raw.startswith("file:") or raw.startswith("local:"):
        path = default_path
        if raw.startswith("sqlite:"):
            path = raw[7:] or default_path
        elif raw.startswith("file:"):
            path = raw[5:] or default_path
        elif raw.startswith("local:"):
            path = raw[6:] or default_path
        queue = DurableQueue(path, lease_seconds=lease_seconds, max_attempts=max_attempts)
        return {"ready": True, "backend": "sqlite", "queue": queue, "reason": ""}
    if raw.startswith(("redis://", "rediss://")):
        return {
            "ready": False,
            "backend": "redis",
            "queue": None,
            "reason": "REDIS_URL is set but the Redis durable-queue adapter is not wired yet",
        }
    return {"ready": False, "backend": "unknown", "queue": None,
            "reason": "queue URI must be sqlite:/file:/local: or redis://"}
