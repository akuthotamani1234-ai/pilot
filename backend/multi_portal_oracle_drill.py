"""Gate C: multi-portal approved-spec oracle bind suite.

Binds fixture features from DemoStore, ClassicShop, AdminPortal, and TravelSite
truth files; proves AI proposals stay needs_review. Broader live portal
oracles still open — ``gate_c_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .finalization import folder_is_linked, write_text_unless_linked
from .oracle import decide_observation
from .oracle_bind import attach_assertion

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "multi_portal_oracle_drill.json"

PORTALS = (
    ("DemoStore", ROOT / "tests" / "demo_store_truth.json"),
    ("ClassicShop", ROOT / "tests" / "classic_shop_truth.json"),
    ("AdminPortal", ROOT / "tests" / "truth" / "admin_portal.json"),
    ("TravelSite", ROOT / "tests" / "truth" / "travel_site.json"),
)


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _refused_portal(name: str, path: Path) -> dict:
    return {
        "portal": name,
        "truth": _label(path),
        "features_bound": 0,
        "rows": [],
        "ai_accepted": False,
        "ai_verdict": "needs_review",
        "ok": False,
    }


def _bind_portal(name: str, path: Path, *, limit: int = 3) -> dict:
    if folder_is_linked(path) or not path.is_file():
        return _refused_portal(name, path)
    truth = json.loads(path.read_text(encoding="utf-8"))
    features = list(truth.get("features") or [])[:limit]
    rows = []
    verdicts = []
    for feat in features:
        case = attach_assertion({
            "tc_id": f"{name}-{feat.get('id')}",
            "title": str(feat.get("id") or ""),
            "expected": f"{name} feature {feat.get('id')}: {feat.get('test') or ''}",
            "oracle": "fixture",
            "url": str(feat.get("page") or "/"),
            "page": str(feat.get("page") or "/"),
        })
        decision = decide_observation(
            case["assertion"],
            observed=str(feat.get("test") or "ok"),
            matched=True,
        )
        rows.append({
            "id": feat.get("id"),
            "accepted": bool(case["assertion"].get("accepted")),
            "verdict": decision.get("verdict"),
        })
        verdicts.append(decision.get("verdict"))
    ai = attach_assertion({
        "tc_id": f"{name}-AI-001",
        "title": f"{name} unreviewed AI guess",
        "expected": "Maybe wrong",
        "oracle": "ai",
        "url": "/",
    })
    ai_decision = decide_observation(ai["assertion"], observed="x", matched=False)
    ok = (
        bool(rows)
        and all(r.get("accepted") for r in rows)
        and all(v == "pass" for v in verdicts)
        and not bool(ai["assertion"].get("accepted"))
        and ai_decision.get("verdict") == "needs_review"
    )
    return {
        "portal": name,
        "truth": _label(path),
        "features_bound": len(rows),
        "rows": rows,
        "ai_accepted": bool(ai["assertion"].get("accepted")),
        "ai_verdict": ai_decision.get("verdict"),
        "ok": ok,
    }


def _linked_drill() -> dict:
    return {
        "gate_c_complete": False,
        "ok": False,
        "drill": "multi_portal_oracle_bind",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_multi_portal_oracle_drill(*, ops_dir: Path | None = None) -> dict:
    out_name = "multi_portal_oracle_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    portals = [_bind_portal(name, path) for name, path in PORTALS]
    passed = sum(1 for p in portals if p.get("ok"))
    evidence = {
        "gate_c_complete": False,
        "drill": "multi_portal_oracle_bind",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "portals": portals,
        "passed": passed,
        "total": len(portals),
        "ok": passed == len(portals),
        "reason": (
            f"Multi-portal oracle bind {passed}/{len(portals)} fixtures ok; "
            "broader live portal oracle paths still open"
        ),
    }
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_drill()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, json.dumps(evidence, indent=2)):
        return _linked_drill()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "multi_portal_oracle_drill.json"
        if not folder_is_linked(art) and not folder_is_linked(art.parent):
            art.parent.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art.parent, art.name, json.dumps(evidence, indent=2))
    return evidence
