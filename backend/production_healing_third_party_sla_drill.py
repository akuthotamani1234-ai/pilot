"""Gate E: third-party / production healing SLA contract (not executed).

Records SLA fields expected before a production healing suite can close.
Does **not** run against third-party production — ``gate_e_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_third_party_sla_drill.json"

LOCAL_PARTIAL = (
    "production_healing_contract_drill.json",
    "production_healing_taxonomy_drill.json",
    "production_healing_flaky_policy_drill.json",
    "production_healing_replay_pack_drill.json",
    "production_healing_readiness_drill.json",
    "production_healing_suite_pack_drill.json",
    "multi_app_healing_suite_drill.json",
)


def _linked_sla() -> dict:
    return {
        "gate_e_complete": False,
        "ok": False,
        "drill": "production_healing_third_party_sla",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_production_healing_third_party_sla_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    name = "production_healing_third_party_sla_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_sla()

    ops = ROOT / "docs" / "ops-evidence"
    present = [
        n for n in LOCAL_PARTIAL
        if not folder_is_linked(ops / n) and (ops / n).is_file()
    ]
    sla = {
        "target_class": "authorized_third_party_or_staging",
        "max_heal_latency_ms": 30_000,
        "locator_only_auto_apply": True,
        "human_review_required_for": [
            "assertion_change",
            "auth_bypass",
            "infra_skip",
            "flaky_quarantine",
        ],
        "required_artifacts": [
            "before_after_replay",
            "taxonomy_classification",
            "regression_package",
            "heal_proposal_log",
        ],
        "acceptance": [
            "Seeded + organic failures reproduce deterministically",
            "Locator-only heals pass regression",
            "Non-locator proposals stay pending human review",
            "No irreversible write-guard weakening",
        ],
        "note": "SLA recorded locally; production / third-party suite still open",
    }
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_third_party_sla",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "contract_only",
        "sla": sla,
        "production_suite_executed": False,
        "local_partial_present": present,
        "local_partial_missing": [n for n in LOCAL_PARTIAL if n not in present],
        "ok": len(present) == len(LOCAL_PARTIAL),
        "reason": (
            f"Third-party healing SLA recorded "
            f"({len(present)}/{len(LOCAL_PARTIAL)} local partials present); "
            "production / third-party healing suite still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_sla()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_sla()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
