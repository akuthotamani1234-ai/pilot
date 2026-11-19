"""Gate J: ClassicShop mutation score from Gate J accuracy evidence.

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
EVIDENCE = ROOT / "docs" / "ops-evidence" / "classic_mutation_score_drill.json"
RUN2 = ROOT / "deep_validation" / "live_runs" / "phase1_classic_shop_run2_summary.json"
TRUTH = ROOT / "tests" / "classic_shop_truth.json"


def _source(path: Path) -> str | None:
    if folder_is_linked(path) or not path.is_file():
        return None
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _planted_ids(path: Path) -> list[str]:
    if folder_is_linked(path) or not path.is_file():
        return []
    truth = json.loads(path.read_text(encoding="utf-8"))
    bugs = truth.get("bugs") or {}
    if isinstance(bugs, dict):
        return list(bugs.keys())
    if isinstance(bugs, list):
        return [str(b.get("id") or b) for b in bugs]
    return []


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
        "drill": "mutation_score_classic_shop",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_classic_mutation_score_drill(*, ops_dir: Path | None = None) -> dict:
    out_name = "classic_mutation_score_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    planted_ids = _planted_ids(TRUTH)
    planted = [{"id": bid} for bid in planted_ids]
    reported = _reported(RUN2)
    source = _source(RUN2)

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
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, json.dumps(evidence, indent=2)):
        return _linked_drill()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "classic_mutation_score_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
