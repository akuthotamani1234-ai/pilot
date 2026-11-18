"""Gate J: AdminPortal + TravelSite mutation scores from accuracy runs.

Scores planted seeded defects against reported catches. Broader third-party
mutation suites still open — ``gate_j_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .mutation_score import score_planted

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "fixture_mutation_suite_drill.json"

SUITES = (
    {
        "id": "admin_portal",
        "truth": ROOT / "tests" / "truth" / "admin_portal.json",
        "summary": ROOT / "deep_validation" / "live_runs" / "phase1_admin_portal_run4_summary.json",
    },
    {
        "id": "travel_site",
        "truth": ROOT / "tests" / "truth" / "travel_site.json",
        "summary": ROOT / "deep_validation" / "live_runs" / "phase1_travel_site_run2_summary.json",
    },
)


def _planted_ids(truth_path: Path) -> list[str]:
    if not truth_path.is_file():
        return []
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    bugs = truth.get("bugs") or {}
    if isinstance(bugs, dict):
        return list(bugs.keys())
    if isinstance(bugs, list):
        return [str(b.get("id") or b) for b in bugs]
    return []


def _reported(summary_path: Path) -> tuple[list[str], str | None]:
    if not summary_path.is_file():
        return [], None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        bugs = ((payload.get("buggy") or {}).get("bugs") or {})
        return list(bugs.get("caught") or []), str(summary_path.relative_to(ROOT))
    except (OSError, ValueError):
        return [], str(summary_path.relative_to(ROOT))


def run_fixture_mutation_suite_drill(*, ops_dir: Path | None = None) -> dict:
    rows = []
    for suite in SUITES:
        planted_ids = _planted_ids(suite["truth"])
        reported, source = _reported(suite["summary"])
        scored = score_planted([{"id": i} for i in planted_ids], reported)
        ok = (
            bool(planted_ids)
            and len(scored.get("missed") or []) == 0
            and len(scored.get("false_reports") or []) == 0
            and len(scored.get("caught") or []) == len(planted_ids)
        )
        rows.append({
            "fixture": suite["id"],
            "source": source,
            "planted": planted_ids,
            "reported": reported,
            "score": scored,
            "ok": ok,
        })
    passed = sum(1 for r in rows if r.get("ok"))
    evidence = {
        "gate_j_complete": False,
        "drill": "fixture_mutation_suite",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "suites": rows,
        "passed": passed,
        "total": len(rows),
        "ok": passed == len(rows) and bool(rows),
        "reason": (
            f"Fixture mutation suite {passed}/{len(rows)} "
            "(AdminPortal + TravelSite); broader third-party suites still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "fixture_mutation_suite_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "fixture_mutation_suite_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
