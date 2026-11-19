"""Gate I: OIDC claim-map completeness (local ACL coverage, not hosted SSO).

Scores whether tid/email/org/hd/groups claim mappers have local evidence.
Does **not** perform live hosted IdP Studio SSO — ``gate_i_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "hosted_idp_claim_map_completeness_drill.json"

CLAIM_MAP = (
    ("tid", "oidc_tid_tenant_acl_drill.json", "tid → tenant ACL"),
    ("email_domain", "oidc_email_domain_tenant_acl_drill.json", "email domain → tenant ACL"),
    ("org", "oidc_org_tenant_acl_drill.json", "org claim → tenant ACL"),
    ("hd", "oidc_org_tenant_acl_drill.json", "hd claim → tenant ACL"),
    ("groups", "oidc_groups_role_acl_drill.json", "groups → role ACL"),
    ("matrix", "oidc_acl_matrix_pack_drill.json", "ACL matrix pack"),
    ("principal", "studio_sso_principal_bootstrap_drill.json", "SSO principal bootstrap"),
    ("callback", "studio_oidc_callback_drill.json", "Studio /api/sso/callback"),
)


def run_hosted_idp_claim_map_completeness_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for claim, artifact, label in CLAIM_MAP:
        ready = (ops / artifact).is_file()
        rows.append({
            "claim": claim,
            "artifact": artifact,
            "label": label,
            "ready": ready,
        })
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_i_complete": False,
        "drill": "hosted_idp_claim_map_completeness",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "readiness_score_only",
        "score": score,
        "score_of": len(CLAIM_MAP),
        "claims": rows,
        "live_hosted_sso": False,
        "ok": score == len(CLAIM_MAP),
        "reason": (
            f"OIDC claim-map completeness {score}/{len(CLAIM_MAP)}; "
            "live hosted IdP Studio SSO still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "hosted_idp_claim_map_completeness_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "hosted_idp_claim_map_completeness_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
