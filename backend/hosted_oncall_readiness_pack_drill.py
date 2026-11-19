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


def run_hosted_oncall_readiness_pack_drill(*, ops_dir: Path | None = None) -> dict:
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
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_oncall_readiness_pack_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_oncall_readiness_pack_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
