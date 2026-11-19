"""Gate J / QX-A09: mutation score drill from DemoStore Gate J evidence.

Scores planted seeded defects against reported catches using
``mutation_score.score_planted``. Broader third-party mutation suites still
open — ``gate_j_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .finalization import folder_is_linked, write_text_unless_linked
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


def _source(path: Path) -> str | None:
    if folder_is_linked(path) or not path.is_file():
        return None
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _reported(path: Path) -> list[str]:
    if folder_is_linked(path) or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        bugs = ((payload.get("buggy") or {}).get("bugs") or {})
        return list(bugs.get("caught") or [])
    except (OSError, ValueError):
        return []


def _linked_drill() -> dict:
    return {
        "gate_j_complete": False,
        "ok": False,
        "drill": "mutation_score_demostore",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_mutation_score_drill(*, ops_dir: Path | None = None) -> dict:
    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_drill()
    reported = _reported(RUN7)
    source = _source(RUN7)

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
    out = (Path(ops_dir) / "mutation_score_drill.json") if ops_dir else EVIDENCE
    if folder_is_linked(dest) or folder_is_linked(out):
        return _linked_drill()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out.name, json.dumps(evidence, indent=2)):
        return _linked_drill()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "mutation_score_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
