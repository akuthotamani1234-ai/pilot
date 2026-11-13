"""Finite phase budgets that preserve execution time and deterministic reporting."""
import json
import time
from pathlib import Path


def discovery_minutes(config) -> float:
    if config.discovery_only or config.run_time_limit_min <= 0:
        return config.crawl_time_limit_min
    return min(config.crawl_time_limit_min, config.run_time_limit_min * config.discovery_budget_fraction)


def work_seconds(limit_min: float, reserve_s: float) -> float:
    return max(0.001, limit_min * 60 - min(max(0, reserve_s), limit_min * 30))


def record_phase(root: Path, name: str, started: float, status: str) -> None:
    with (root / "phase_timings.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"phase": name, "duration_s": round(time.monotonic() - started, 3),
                                 "status": status}) + "\n")
