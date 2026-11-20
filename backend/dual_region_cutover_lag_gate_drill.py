"""Gate H: block cutover when measured failover exceeds the lag contract.

Compares local Postgres/Redis/MinIO failover elapsed time to the replication
lag budgets (30s / 5s / 60s). Does **not** prove hosted multi-region DR —
``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "dual_region_cutover_lag_gate_drill.json"

# Same budgets as dual_region_replication_lag_contract_drill.
LAG_BUDGET_S = {
    "postgres": 30,
    "redis": 5,
    "minio": 60,
}


def evaluate_cutover_lag(stores: list[dict]) -> dict:
    """Return per-store lag decisions. Over budget or a failed store blocks cutover."""
    rows = []
    for row in stores:
        name = str(row.get("store") or "")
        budget_s = LAG_BUDGET_S.get(name)
        elapsed_ms = int(row.get("elapsed_ms") or 0)
        store_ok = bool(row.get("ok"))
        over = budget_s is None or (not store_ok) or elapsed_ms > budget_s * 1000
        rows.append({
            "store": name,
            "ok": store_ok,
            "elapsed_ms": elapsed_ms,
            "budget_s": budget_s,
            "over_budget": over,
        })
    return {
        "stores": rows,
        "cutover_blocked": any(item["over_budget"] for item in rows),
    }


def _linked_lag() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "dual_region_cutover_lag_gate",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_dual_region_cutover_lag_gate_drill(*, ops_dir: Path | None = None) -> dict:
    from .failover_rto_drill import run_failover_rto_drill
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "dual_region_cutover_lag_gate_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_lag()

    measured = run_failover_rto_drill(ops_dir=ops_dir)
    decision = evaluate_cutover_lag(list(measured.get("stores") or []))
    known = [row for row in decision["stores"] if row["store"] in LAG_BUDGET_S]
    ok = len(known) == len(LAG_BUDGET_S) and all(row["ok"] for row in known)
    evidence = {
        "gate_h_complete": False,
        "drill": "dual_region_cutover_lag_gate",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_lag_gate",
        "budgets_s": LAG_BUDGET_S,
        "measured": decision["stores"],
        "cutover_blocked": decision["cutover_blocked"],
        "live_hosted_dr": False,
        "ok": ok,
        "reason": (
            "Local cutover lag gate evaluated "
            f"({len(known)}/{len(LAG_BUDGET_S)} stores, "
            f"cutover_blocked={str(decision['cutover_blocked']).lower()}); "
            "live hosted multi-region DR / on-call still open"
            if ok else
            "Local cutover lag gate incomplete; hosted multi-region DR still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_lag()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_lag()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
