"""Gate J / QX-A09: mutation score drill from DemoStore Gate J evidence.

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
EVIDENCE = ROOT / "docs" / "ops-evidence" / "mutation_score_drill.json"
RUN7 = ROOT / "deep_validation" / "live_runs" / "phase1_demo_store_run7_summary.json"

# Canonical DemoStore planted defect ids (Gate J fixture).
PLANTED = [
    {"id": "cart_total"},
    {"id": "dead_button"},
    {"id": "qty_below_min"},
    {"id": "search_wrong_hit"},
    {"id": "sort_price"},
    {"id": "wishlist_error"},
]


def run_mutation_score_drill(*, ops_dir: Path | None = None) -> dict:
    reported: list[str] = []
    source = str(RUN7.relative_to(ROOT)) if RUN7.is_file() else None
    if RUN7.is_file():
        try:
            payload = json.loads(RUN7.read_text(encoding="utf-8"))
            bugs = ((payload.get("buggy") or {}).get("bugs") or {})
            reported = list(bugs.get("caught") or [])
        except (OSError, ValueError):
            reported = []

    scored = score_planted(PLANTED, reported)
    evidence = {
        "gate_j_complete": False,
        "drill": "mutation_score_demostore",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": source,
        "planted": [row["id"] for row in PLANTED],
        "reported": reported,
        "score": scored,
        "ok": (
            len(scored.get("missed") or []) == 0
            and len(scored.get("false_reports") or []) == 0
            and len(scored.get("caught") or []) == len(PLANTED)
        ),
        "reason": (
            f"DemoStore mutation score {len(scored.get('caught') or [])}/{len(PLANTED)} "
            f"caught, {len(scored.get('missed') or [])} missed, "
            f"{len(scored.get('false_reports') or [])} false reports; "
            "broader third-party mutation suites still open"
        ),
    }

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "mutation_score_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "mutation_score_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
