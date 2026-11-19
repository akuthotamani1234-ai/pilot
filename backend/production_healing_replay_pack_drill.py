"""Gate E: production-like healing before/after replay pack (fixtures only).

Builds a hashed before→after locator-repair package from the multi-app healing
suite. Does **not** run against third-party production —
``gate_e_complete`` stays False.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .healing_policy import review_repair

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "production_healing_replay_pack_drill.json"

APPS = ("demo_store", "classic_shop", "admin_portal", "travel_site")


def _pair(app_id: str) -> dict:
    before = (
        f"def test_{app_id}(page):\n"
        f"    page.locator(\"#qpilot-missing-{app_id}\").click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    after = (
        f"def test_{app_id}(page):\n"
        "    page.locator(\"a, button\").first.click()\n"
        "    assert page.locator(\"body\").is_visible()\n"
    )
    weaken = (
        f"def test_{app_id}(page):\n"
        f"    page.locator(\"#qpilot-missing-{app_id}\").click()\n"
        "    assert True\n"
    )
    allow = review_repair(before, after)
    deny = review_repair(before, weaken)
    payload = {
        "app": app_id,
        "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(after.encode()).hexdigest(),
        "locator_repair_allowed": bool(allow.get("allowed")),
        "weaken_denied": not bool(deny.get("allowed")),
    }
    payload["ok"] = payload["locator_repair_allowed"] and payload["weaken_denied"]
    return payload


def run_production_healing_replay_pack_drill(*, ops_dir: Path | None = None) -> dict:
    from .multi_app_healing_suite_drill import run_multi_app_healing_suite_drill
    from .production_healing_contract_drill import run_production_healing_contract_drill

    suite = run_multi_app_healing_suite_drill(ops_dir=ops_dir)
    contract = run_production_healing_contract_drill(ops_dir=ops_dir)
    pairs = [_pair(app_id) for app_id in APPS]
    passed = sum(1 for row in pairs if row.get("ok"))
    pack_body = json.dumps({"pairs": pairs, "suite_ok": suite.get("ok")}, sort_keys=True)
    evidence = {
        "gate_e_complete": False,
        "drill": "production_healing_replay_pack",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": "fixture_replay_pack",
        "apps": list(APPS),
        "pairs": pairs,
        "passed": passed,
        "pack_sha256": hashlib.sha256(pack_body.encode()).hexdigest(),
        "suite_ok": bool(suite.get("ok")),
        "contract_ok": bool(contract.get("ok")),
        "ok": passed == len(APPS) and bool(suite.get("ok")) and bool(contract.get("ok")),
        "reason": (
            f"Production healing replay pack {passed}/{len(APPS)} apps hashed; "
            "production / third-party healing suite still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "production_healing_replay_pack_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "production_healing_replay_pack_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
