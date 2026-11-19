"""Gate H: paging escalation + ack→resolve combined pack (loopback).

Runs primary→secondary escalation then ack/resolve lifecycle as one ops pack.
Live hosted on-call paging still open — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "paging_escalation_ack_pack_drill.json"


def _linked_pack() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "paging_escalation_ack_pack",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_paging_escalation_ack_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "paging_escalation_ack_pack_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_pack()

    from .paging_ack_drill import run_paging_ack_drill
    from .paging_escalation_drill import run_paging_escalation_drill

    started = time.perf_counter()
    try:
        escalation = run_paging_escalation_drill(ops_dir=ops_dir)
    except Exception as exc:
        escalation = {"ok": False, "reason": str(exc)[:160]}
    try:
        ack = run_paging_ack_drill(ops_dir=ops_dir)
    except Exception as exc:
        ack = {"ok": False, "reason": str(exc)[:160]}
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ok = bool(escalation.get("ok")) and bool(ack.get("ok"))
    evidence = {
        "gate_h_complete": False,
        "drill": "paging_escalation_ack_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "loopback_ops_pack",
        "escalation_ok": bool(escalation.get("ok")),
        "ack_ok": bool(ack.get("ok")),
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "reason": (
            f"Paging escalation+ack pack ok in {elapsed_ms}ms; "
            "live hosted on-call paging still open"
            if ok else
            "Paging escalation+ack pack incomplete; hosted on-call still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_pack()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_pack()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
