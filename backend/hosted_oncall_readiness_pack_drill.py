"""Gate H: hosted on-call readiness pack (contract + readiness + paging pack).

Bundles local on-call contract/readiness with escalation+ack pack evidence.
Does **not** page a live hosted on-call — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_oncall_readiness_pack_drill.json"


def _linked_pack() -> dict:
    return {
        "gate_h_complete": False,
        "ok": False,
        "drill": "hosted_oncall_readiness_pack",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_hosted_oncall_readiness_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "hosted_oncall_readiness_pack_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_pack()

    from .hosted_oncall_contract_drill import run_hosted_oncall_contract_drill
    from .hosted_oncall_readiness_drill import run_hosted_oncall_readiness_drill
    from .paging_escalation_ack_pack_drill import run_paging_escalation_ack_pack_drill

    started = time.perf_counter()
    try:
        contract = run_hosted_oncall_contract_drill(ops_dir=ops_dir)
    except Exception as exc:
        contract = {"ok": False, "reason": str(exc)[:160]}
    try:
        readiness = run_hosted_oncall_readiness_drill(ops_dir=ops_dir)
    except Exception as exc:
        readiness = {"ok": False, "reason": str(exc)[:160]}
    try:
        paging = run_paging_escalation_ack_pack_drill(ops_dir=ops_dir)
    except Exception as exc:
        paging = {"ok": False, "reason": str(exc)[:160]}
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    ok = (
        bool(contract.get("ok"))
        and bool(readiness.get("ok"))
        and bool(paging.get("ok"))
    )
    evidence = {
        "gate_h_complete": False,
        "drill": "hosted_oncall_readiness_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "local_ops_pack",
        "contract_ok": bool(contract.get("ok")),
        "readiness_ok": bool(readiness.get("ok")),
        "paging_pack_ok": bool(paging.get("ok")),
        "live_hosted_paging": False,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "reason": (
            f"Hosted on-call readiness pack ok in {elapsed_ms}ms; "
            "live hosted multi-region DR / on-call paging still open"
            if ok else
            "Hosted on-call readiness pack incomplete; hosted on-call still open"
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
