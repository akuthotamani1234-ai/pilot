"""Gate G: independent review scope matrix (unsigned).

Maps gates A–J to representative ops-evidence artifacts for reviewers.
Does **not** collect a signature — ``signed_off`` / ``gate_g_complete`` stay False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "independent_review_scope_matrix_drill.json"

SCOPE = (
    ("A", "Durable swarm / checkpoint", ("swarm_control_drill.json", "redis_durable_queue_drill.json")),
    ("B", "DemoStore mutation / seeded defects", ("mutation_score_drill.json",)),
    ("C", "Classic/Admin/Travel mutation", ("classic_mutation_score_drill.json",)),
    ("D", "Android / multi-device CI", (
        "android_device_ci_readiness_pack_drill.json",
        "hosted_ci_artifact_gate_pack_drill.json",
    )),
    ("E", "Production healing suite", (
        "production_healing_acceptance_gate_drill.json",
        "production_healing_suite_pack_drill.json",
    )),
    ("F", "Multi-browser portfolio CI", (
        "browser_portfolio_ci_readiness_pack_drill.json",
        "multi_browser_portfolio_suite_drill.json",
    )),
    ("G", "Independent review sign-off", (
        "independent_review_handoff_pack_drill.json",
        "independent_review_findings_template_drill.json",
        "INDEPENDENT_REVIEW_FINDINGS.md",
    )),
    ("H", "Hosted multi-region DR / on-call", (
        "hosted_dr_cutover_checklist_drill.json",
        "multi_region_dr_readiness_pack_drill.json",
    )),
    ("I", "Hosted IdP Studio SSO", (
        "studio_sso_login_path_drill.json",
        "hosted_idp_claim_map_completeness_drill.json",
        "oidc_acl_matrix_pack_drill.json",
    )),
    ("J", "Benchmark / seeded demos", ("remaining_blockers.json",)),
)


def run_independent_review_scope_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for gate, label, artifacts in SCOPE:
        present = [a for a in artifacts if (ops / a).is_file()]
        rows.append({
            "gate": gate,
            "label": label,
            "artifacts": list(artifacts),
            "present": present,
            "ready": len(present) == len(artifacts),
            "reviewed": False,
        })
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_g_complete": False,
        "drill": "independent_review_scope_matrix",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "unsigned_scope_matrix",
        "gates": rows,
        "score": score,
        "score_of": len(SCOPE),
        "signed_off": False,
        "ok": score >= 8 and not any(row["reviewed"] for row in rows),
        "reason": (
            f"Independent review scope matrix {score}/{len(SCOPE)} (unsigned); "
            "external sign-off still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "independent_review_scope_matrix_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "independent_review_scope_matrix_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
