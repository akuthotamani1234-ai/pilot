"""Gate E: production healing fixture coverage map (local demos only).

Maps demo fixtures to healing evidence classes. Does **not** run a production /
third-party suite — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_fixture_coverage_drill.json"

COVERAGE = (
    ("demostore", "live_failure_matrix_drill.json", "DemoStore failure matrix"),
    ("demostore_heal", "demo_store_healing_live_drill.json", "DemoStore live healing"),
    ("classic", "classic_mutation_score_drill.json", "Classic shop mutation"),
    ("admin", "admin_portal_lifecycle_drill.json", "Admin portal lifecycle"),
    ("travel", "multi_app_healing_suite_drill.json", "Travel via multi-app suite"),
    ("multi_app", "multi_app_healing_suite_drill.json", "4-demo healing suite"),
    ("taxonomy", "production_healing_taxonomy_drill.json", "Failure taxonomy"),
    ("replay", "production_healing_replay_pack_drill.json", "Before/after replay"),
    ("flaky_policy", "production_healing_flaky_policy_drill.json", "No-auto-apply policy"),
    ("acceptance", "production_healing_acceptance_gate_drill.json", "Local acceptance gate"),
    ("seed_catalog", "production_healing_seed_catalog_drill.json", "Seed catalog"),
    ("suite_pack", "production_healing_suite_pack_drill.json", "Local suite pack"),
)


def _linked_coverage() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "production_healing_fixture_coverage",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_production_healing_fixture_coverage_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "production_healing_fixture_coverage_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_coverage()

    ops = ROOT / "docs" / "ops-evidence"
    rows = []
    for fixture_id, artifact, label in COVERAGE:
        path = ops / artifact
        ready = (not folder_is_linked(path)) and path.is_file()
        rows.append({
            "id": fixture_id,
            "artifact": artifact,
            "label": label,
            "ready": ready,
            "production_covered": False,
        })
    score = sum(1 for row in rows if row["ready"])
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_fixture_coverage",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "fixture_coverage_local_only",
        "coverage": rows,
        "score": score,
        "score_of": len(COVERAGE),
        "production_suite_executed": False,
        "ok": score == len(COVERAGE),
        "reason": (
            f"Production healing fixture coverage {score}/{len(COVERAGE)}; "
            "production / third-party healing suite still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_coverage()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_coverage()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
