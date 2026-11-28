"""Large executions: hundreds or thousands of requirement test cases, run in batches through the existing engine.

  split      batches of at most BATCH_SIZE cases (QPILOT_BATCH_SIZE, default 20) - a case and its prerequisite chain
             stay in ONE batch (they set up their own state together), high-priority cases first, then by id; a
             chain larger than a batch stays whole (never cut)
  order      the batches run one after another (the Studio runs one test at a time: controlled concurrency, no
             unbounded agents, each AI prompt sees one batch only); each batch's results are collected as soon as it
             ends (incremental reporting)
  checkpoint the execution stores every batch's state (queued / running / done / failed / cancelled / interrupted)
             and run; a Studio restart leaves the running batch 'interrupted' and the execution resumable - resume
             continues with the first batch not done (a typed password is never stored: it is asked again)
  cost       AI calls, tokens and estimated cost are summed from each batch run's own cost.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path

BATCH_SIZE = max(1, int(os.environ.get("QPILOT_BATCH_SIZE", "20")))
PRIORITY = {"high": 0, "medium": 1, "low": 2}


def split(cases: list[dict], chains: dict[str, list[str]], size: int | None = None,
          validated: set[str] | None = None) -> list[list[str]]:
    """Case ids in batches; each case's prerequisite chain stays in its batch."""
    size = size or BATCH_SIZE
    ids = [c["id"] for c in cases]
    by_id = {c["id"]: c for c in cases}
    group_of: dict[str, int] = {}
    groups: list[set[str]] = []
    for cid in ids:  # (connected components of "needs" - a chain is never cut)
        members = {cid, *chains.get(cid, [])}
        hit = sorted({group_of[m] for m in members if m in group_of})
        if hit:
            target = hit[0]
            for other in hit[1:]:
                groups[target] |= groups[other]
                for m in groups[other]:
                    group_of[m] = target
                groups[other] = set()
        else:
            groups.append(set())
            target = len(groups) - 1
        groups[target] |= members
        for m in members:
            group_of[m] = target
    order = sorted((g for g in groups if g), key=lambda g: (bool(validated) and not g.issubset(validated),
                                                         min(PRIORITY.get(str((by_id.get(m) or {})
                                                                                   .get("priority")), 1) for m in g),
                                                           min(g)))
    batches: list[list[str]] = []
    for g in order:
        members = sorted(g, key=lambda m: (len(chains.get(m, [])), m))  # (prerequisites first in a batch)
        if batches and len(batches[-1]) + len(members) <= size:
            batches[-1].extend(members)
        else:
            batches.append(members)
    return batches


def plan_batches(case_ids: list[str], cases: list[dict], chains: dict[str, list[str]],
                 size: int | None = None, validated: set[str] | None = None) -> list[dict]:
    wanted = set(case_ids)
    return [{"n": i + 1, "case_ids": [c for c in b if c in wanted], "status": "queued", "run_id": ""}
            for i, b in enumerate(split([c for c in cases if c["id"] in wanted], chains, size, validated))]


def next_batch(ex: dict) -> dict | None:
    return next((b for b in ex.get("batches") or [] if b["status"] in ("queued", "interrupted")), None)


def cost_of(run_dirs: list[Path]) -> dict:
    total = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    for d in run_dirs:
        f = Path(d) / "cost.json"
        try:
            c = json.loads(f.read_text(encoding="utf-8")) if f.is_file() and not f.is_symlink() else {}
        except (OSError, ValueError):
            c = {}
        for k in total:
            total[k] += c.get(k) or 0
    total["cost_usd"] = round(total["cost_usd"], 6)
    return total
