"""Gate E: production healing seed catalog (fixtures, not third-party live).

Catalogs seeded failure classes and local evidence needed before a third-party
healing suite can run. Does **not** execute production suite —
``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_seed_catalog_drill.json"

SEEDS = (
    ("locator", "live_failure_matrix_drill.json", "Missing/stale locator"),
    ("product_defect", "demo_store_healing_live_drill.json", "Seeded product defect"),
    ("auth_problem", "production_healing_flaky_policy_drill.json", "Auth redirect / 401"),
    ("infrastructure", "production_healing_flaky_policy_drill.json", "Connection refused"),
    ("timeout", "production_healing_taxonomy_drill.json", "Hard timeout"),
    ("flaky", "production_healing_flaky_policy_drill.json", "Flaky retry class"),
    ("multi_app", "multi_app_healing_suite_drill.json", "4-demo fixture suite"),
    ("replay", "production_healing_replay_pack_drill.json", "Before/after replay"),
    ("sla", "production_healing_third_party_sla_drill.json", "Third-party SLA"),
    ("suite_pack", "production_healing_suite_pack_drill.json", "Local suite pack"),
)


def run_production_healing_seed_catalog_drill(*, ops_dir: Path | None = None) -> dict:
    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for seed_id, artifact, label in SEEDS:
        ready = (ops / artifact).is_file()
        rows.append({
            "id": seed_id,
            "artifact": artifact,
            "label": label,
            "ready": ready,
            "production_seeded": False,
        })
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_seed_catalog",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "seed_catalog_local_only",
        "seeds": rows,
        "score": score,
        "score_of": len(SEEDS),
        "production_suite_executed": False,
        "ok": score == len(SEEDS),
        "reason": (
            f"Production healing seed catalog {score}/{len(SEEDS)}; "
            "production / third-party healing suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "production_healing_seed_catalog_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "production_healing_seed_catalog_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
