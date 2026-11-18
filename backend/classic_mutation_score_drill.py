"""Gate J: ClassicShop mutation score from Gate J accuracy evidence.

Scores planted seeded defects against reported catches using
``mutation_score.score_planted``. Broader third-party mutation suites still
open — ``gate_j_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .mutation_score import score_planted

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "classic_mutation_score_drill.json"
RUN2 = ROOT / "deep_validation" / "live_runs" / "phase1_classic_shop_run2_summary.json"
TRUTH = ROOT / "tests" / "classic_shop_truth.json"


def run_classic_mutation_score_drill(*, ops_dir: Path | None = None) -> dict:
    planted_ids: list[str] = []
    if TRUTH.is_file():
        truth = json.loads(TRUTH.read_text(encoding="utf-8"))
        bugs = truth.get("bugs") or {}
        if isinstance(bugs, dict):
            planted_ids = list(bugs.keys())
        elif isinstance(bugs, list):
            planted_ids = [str(b.get("id") or b) for b in bugs]
    planted = [{"id": bid} for bid in planted_ids]

    reported: list[str] = []
    source = str(RUN2.relative_to(ROOT)) if RUN2.is_file() else None
    if RUN2.is_file():
        try:
            payload = json.loads(RUN2.read_text(encoding="utf-8"))
            bugs = ((payload.get("buggy") or {}).get("bugs") or {})
            reported = list(bugs.get("caught") or [])
        except (OSError, ValueError):
            reported = []

    scored = score_planted(planted, reported)
    evidence = {
        "gate_j_complete": False,
        "drill": "mutation_score_classic_shop",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "planted": planted_ids,
        "reported": reported,
        "score": scored,
        "ok": (
            bool(planted_ids)
            and len(scored.get("missed") or []) == 0
            and len(scored.get("false_reports") or []) == 0
            and len(scored.get("caught") or []) == len(planted_ids)
        ),
        "reason": (
            f"ClassicShop mutation score {len(scored.get('caught') or [])}/{len(planted_ids)} "
            f"caught, {len(scored.get('missed') or [])} missed, "
            f"{len(scored.get('false_reports') or [])} false reports; "
            "broader third-party mutation suites still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "classic_mutation_score_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "classic_mutation_score_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
