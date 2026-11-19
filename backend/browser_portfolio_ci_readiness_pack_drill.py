"""Gate F: browser portfolio CI readiness pack (local contracts, not hosted).

Bundles multi-browser suite, CI contract, portfolio manifest, dispatch,
upload rehearsal, and hosted CI artifact gate pack. Does **not** run hosted
multi-browser runners — ``gate_f_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "browser_portfolio_ci_readiness_pack_drill.json"

ARTIFACTS = (
    ("multi_browser_portfolio_suite_drill.json", "Multi-browser portfolio suite"),
    ("multi_browser_ci_contract.json", "Multi-browser CI contract"),
    ("portfolio_artifact_manifest_drill.json", "Portfolio artifact manifest"),
    ("workflow_dispatch_contract_drill.json", "workflow_dispatch contracts"),
    ("ci_artifact_upload_rehearsal_drill.json", "CI upload rehearsal"),
    ("hosted_ci_runner_matrix_drill.json", "Hosted CI runner matrix"),
    ("hosted_runner_readiness_drill.json", "Hosted runner readiness"),
    ("hosted_dispatch_payload_rehearsal_drill.json", "Dispatch payload rehearsal"),
    ("hosted_ci_artifact_gate_pack_drill.json", "Hosted CI artifact gate pack"),
    ("hosted_workflow_runner_audit_drill.json", "Hosted workflow runner audit"),
    ("hosted_ci_artifact_retention_contract_drill.json", "Artifact retention contract"),
)


def run_browser_portfolio_ci_readiness_pack_drill(*, ops_dir: Path | None = None) -> dict:
    ops = Path(ops_dir) if ops_dir else (ROOT / "docs" / "ops-evidence")
    rows = []
    for name, label in ARTIFACTS:
        ready = (ops / name).is_file()
        rows.append({"artifact": name, "label": label, "ready": ready})
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_f_complete": False,
        "drill": "browser_portfolio_ci_readiness_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "readiness_score_only",
        "score": score,
        "score_of": len(ARTIFACTS),
        "checks": rows,
        "live_hosted_runners": False,
        "ok": score == len(ARTIFACTS),
        "reason": (
            f"Browser portfolio CI readiness {score}/{len(ARTIFACTS)}; "
            "broad hosted multi-browser runners still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "browser_portfolio_ci_readiness_pack_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "browser_portfolio_ci_readiness_pack_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
