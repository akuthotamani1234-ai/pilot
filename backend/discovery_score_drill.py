"""Gate A: multi-fixture discovery completeness score drill.

Runs AdminPortal / DemoStore / ClassicShop / TravelSite surface inventories and
scores each fixture on pages walked + surface signal keys. Full live discovery
matrix still open — ``gate_a_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "discovery_score_drill.json"

def _truthy_section(section) -> bool:
    if section in (None, 0, [], {}, False, ""):
        return False
    if isinstance(section, dict):
        return any(v not in (None, 0, [], {}, False, "") for v in section.values())
    return True


def _score(evidence: dict) -> dict:
    pages = evidence.get("pages_walked") or []
    surfaces = evidence.get("surfaces") if isinstance(evidence.get("surfaces"), dict) else {}
    keys_hit: list[str] = []
    for key in ("frames", "shadow", "dialogs", "downloads", "lazy", "metadata", "viewports"):
        if _truthy_section(surfaces.get(key)):
            keys_hit.append(key)
    rich = surfaces.get("rich_controls") if isinstance(surfaces.get("rich_controls"), dict) else {}
    for key in ("canvas", "file_upload", "web_component"):
        if rich.get(key):
            keys_hit.append(key)
    page_score = min(1.0, len(pages) / 3.0)
    key_score = min(1.0, len(keys_hit) / 3.0)
    total = round(0.6 * page_score + 0.4 * key_score, 3)
    return {
        "fixture": evidence.get("fixture"),
        "pages": len(pages),
        "surface_keys_hit": keys_hit,
        "score": total,
        "ok": len(pages) >= 2 and total >= 0.4,
    }


def _linked_score() -> dict:
    return {
        "gate_a_complete": False,
        "ok": False,
        "drill": "multi_fixture_discovery_score",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_discovery_score_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "discovery_score_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_score()

    from .surface_evidence_drill import (
        run_admin_portal_surface_drill,
        run_classic_shop_surface_drill,
        run_demo_store_surface_drill,
        run_travel_site_surface_drill,
    )

    # Write per-fixture evidence into ops_dir when provided so tests stay isolated.
    fixtures = [
        run_admin_portal_surface_drill(ops_dir=ops_dir),
        run_demo_store_surface_drill(ops_dir=ops_dir),
        run_classic_shop_surface_drill(ops_dir=ops_dir),
        run_travel_site_surface_drill(ops_dir=ops_dir),
    ]
    scores = [_score(f) for f in fixtures]
    passed = sum(1 for s in scores if s.get("ok"))
    evidence = {
        "gate_a_complete": False,
        "drill": "multi_fixture_discovery_score",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixtures": scores,
        "passed": passed,
        "total": len(scores),
        "ok": passed == len(scores),
        "reason": (
            f"Discovery score {passed}/{len(scores)} fixtures ≥ threshold; "
            "full Gate A live completeness matrix still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_score()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_score()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
