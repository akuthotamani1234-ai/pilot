"""Gate E: production healing suite readiness score (not third-party live).

Scores local failure/healing artifacts against the production contract.
Does **not** run a production / third-party suite — ``gate_e_complete``
stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_readiness_drill.json"

CHECKS = (
    ("live_failure_matrix_drill.json", "Live DemoStore failure matrix"),
    ("multi_app_healing_suite_drill.json", "Multi-app healing suite"),
    ("production_healing_matrix_drill.json", "Production-like healing matrix"),
    ("production_healing_taxonomy_drill.json", "Production healing taxonomy"),
    ("production_healing_contract_drill.json", "Production healing contract"),
    ("production_healing_replay_pack_drill.json", "Before/after replay pack"),
    ("production_healing_flaky_policy_drill.json", "Flaky/auth/infra no-auto-apply"),
    ("healing_regression_drill.json", "Locator-only healing regression"),
    ("production_healing_third_party_sla_drill.json", "Third-party healing SLA"),
    ("production_healing_acceptance_gate_drill.json", "Acceptance gate (local)"),
    ("production_healing_seed_catalog_drill.json", "Seed catalog (local)"),
    ("production_healing_fixture_coverage_drill.json", "Fixture coverage map"),
    ("production_healing_rollback_policy_drill.json", "Rollback / no-apply policy"),
)


def run_production_healing_readiness_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for name, label in CHECKS:
        ready = (ops / name).is_file()
        rows.append({"artifact": name, "label": label, "ready": ready})
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_readiness",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "readiness_score_only",
        "score": score,
        "score_of": len(CHECKS),
        "checks": rows,
        "production_suite_executed": False,
        "ok": score == len(CHECKS),
        "reason": (
            f"Production healing readiness {score}/{len(CHECKS)}; "
            "production / third-party healing suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "production_healing_readiness_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "production_healing_readiness_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
