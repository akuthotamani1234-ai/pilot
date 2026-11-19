"""Gate E: production healing acceptance gate (local criteria, not executed).

Records acceptance criteria that must pass before Gate E can close.
Does **not** run a production / third-party suite — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_acceptance_gate_drill.json"

CRITERIA = (
    ("contract", "production_healing_contract_drill.json", "Healing suite contract present"),
    ("sla", "production_healing_third_party_sla_drill.json", "Third-party SLA recorded"),
    ("taxonomy", "production_healing_taxonomy_drill.json", "Failure taxonomy classified"),
    ("flaky_policy", "production_healing_flaky_policy_drill.json", "Flaky/auth/infra no-auto-apply"),
    ("replay", "production_healing_replay_pack_drill.json", "Before/after replay pack"),
    ("suite_pack", "production_healing_suite_pack_drill.json", "Local suite pack green"),
    ("multi_app", "multi_app_healing_suite_drill.json", "Multi-app fixture suite"),
    ("regression", "healing_regression_drill.json", "Locator-only regression"),
    ("seed_catalog", "production_healing_seed_catalog_drill.json", "Seed catalog ready"),
    ("fixture_coverage", "production_healing_fixture_coverage_drill.json", "Fixture coverage map"),
    ("rollback_policy", "production_healing_rollback_policy_drill.json", "Rollback policy"),
    ("human_loop", "production_healing_human_loop_contract_drill.json", "Human-loop contract"),
)


def _linked_accept() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "production_healing_acceptance_gate",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_production_healing_acceptance_gate_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "production_healing_acceptance_gate_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_accept()

    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for key, artifact, label in CRITERIA:
        path = ops / artifact
        ready = (not folder_is_linked(path)) and path.is_file()
        rows.append({
            "id": key,
            "artifact": artifact,
            "label": label,
            "ready": ready,
            "accepted": False,
        })
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_acceptance_gate",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "acceptance_gate_local_only",
        "score": score,
        "score_of": len(CRITERIA),
        "criteria": rows,
        "production_suite_executed": False,
        "accepted": False,
        "ok": score == len(CRITERIA),
        "reason": (
            f"Production healing acceptance gate local {score}/{len(CRITERIA)}; "
            "production / third-party suite still open (not accepted)"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_accept()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_accept()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
