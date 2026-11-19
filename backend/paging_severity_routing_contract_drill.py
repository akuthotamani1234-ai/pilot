"""Gate H: paging severity → rota routing contract (not live paging).

Maps incident severities to on-call tiers and ack SLAs. Does **not** page a
live rota — ``gate_h_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "paging_severity_routing_contract_drill.json"

LOCAL_PARTIAL = (
    "paging_escalation_drill.json",
    "paging_ack_drill.json",
    "paging_escalation_ack_pack_drill.json",
    "hosted_oncall_rota_contract_drill.json",
    "hosted_oncall_readiness_drill.json",
    "hosted_dr_comms_contract_drill.json",
)

ROUTES = (
    {"severity": "SEV1", "tier": "primary", "ack_sla_minutes": 5, "page_secondary": True},
    {"severity": "SEV2", "tier": "primary", "ack_sla_minutes": 15, "page_secondary": True},
    {"severity": "SEV3", "tier": "secondary", "ack_sla_minutes": 60, "page_secondary": False},
    {"severity": "SEV4", "tier": "ticket_only", "ack_sla_minutes": 240, "page_secondary": False},
)


def run_paging_severity_routing_contract_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    present = [n for n in LOCAL_PARTIAL if (ops / n).is_file()]
    evidence = {
        "gate_h_complete": False,
        "drill": "paging_severity_routing_contract",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "routes": list(ROUTES),
        "live_hosted_paging": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Paging severity routing contract recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials); "
            "live hosted multi-region DR / on-call paging still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "paging_severity_routing_contract_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "paging_severity_routing_contract_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
