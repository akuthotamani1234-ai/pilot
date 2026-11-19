"""Gate A: multi-fixture surface-signal completeness matrix.

Aggregates Admin/Demo/Classic/Travel surface inventories into a signal matrix
(frames, shadow, dialogs, downloads, lazy, metadata, viewports, rich controls).
Full live discovery completeness still open — ``gate_a_complete`` stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "discovery_surface_matrix_drill.json"

SIGNALS = (
    "pages_walked",
    "frames",
    "shadow",
    "dialogs",
    "downloads",
    "lazy",
    "metadata",
    "viewports",
    "canvas",
    "file_upload",
    "web_component",
)

FIXTURE_FILES = (
    ("admin_portal", "admin_portal_surface_coverage.json"),
    ("demo_store", "demo_store_surface_coverage.json"),
    ("classic_shop", "classic_shop_surface_coverage.json"),
    ("travel_site", "travel_site_surface_coverage.json"),
)


def _truthy(section) -> bool:
    if section in (None, 0, [], {}, False, ""):
        return False
    if isinstance(section, dict):
        return any(v not in (None, 0, [], {}, False, "") for v in section.values())
    if isinstance(section, (list, tuple, set)):
        return len(section) > 0
    return True


def _countish(section) -> bool:
    """True when a counter dict has any positive numeric field."""
    if isinstance(section, dict):
        return any(
            isinstance(v, (int, float)) and v > 0
            for v in section.values()
        )
    return _truthy(section)


def _signals_from(payload: dict) -> dict[str, bool]:
    surfaces = payload.get("surfaces") if isinstance(payload.get("surfaces"), dict) else {}
    rich = surfaces.get("rich_controls") if isinstance(surfaces.get("rich_controls"), dict) else {}
    pages = payload.get("pages_walked") or surfaces.get("pages") or []
    # Prefer top-level keys; fall back to nested evidence blob for older artifacts.
    nested = surfaces.get("evidence") if isinstance(surfaces.get("evidence"), dict) else {}
    out = {
        "frames": _countish(surfaces.get("frames")),
        "shadow": _countish(surfaces.get("shadow")),
        "dialogs": _countish(surfaces.get("dialogs")),
        "downloads": _countish(surfaces.get("downloads")),
        "lazy": _countish(surfaces.get("lazy") or nested.get("lazy")),
        "metadata": _countish(surfaces.get("metadata") or nested.get("metadata")),
        "viewports": _countish(surfaces.get("viewports") or nested.get("viewports")),
        "canvas": bool(rich.get("canvas")),
        "file_upload": bool(rich.get("file_upload")),
        "web_component": bool(rich.get("web_component")),
    }
    # Inventory itself is a gate signal when pages were walked.
    out["pages_walked"] = len(pages) >= 2 if isinstance(pages, list) else bool(pages)
    return out


def run_discovery_surface_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    from .surface_evidence_drill import (
        run_admin_portal_surface_drill,
        run_classic_shop_surface_drill,
        run_demo_store_surface_drill,
        run_travel_site_surface_drill,
    )

    # Refresh inventories so the matrix reflects current fixtures.
    run_admin_portal_surface_drill(ops_dir=ops_dir)
    run_demo_store_surface_drill(ops_dir=ops_dir)
    run_classic_shop_surface_drill(ops_dir=ops_dir)
    run_travel_site_surface_drill(ops_dir=ops_dir)

    ops = Path(ops_dir) if ops_dir else (ROOT / "docs" / "ops-evidence")
    rows = []
    for fixture, name in FIXTURE_FILES:
        path = ops / name
        if not path.is_file():
            # Fall back to docs/ops-evidence when ops_dir isolation skipped writes
            path = ROOT / "docs" / "ops-evidence" / name
        payload = {}
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
        signals = _signals_from(payload if isinstance(payload, dict) else {})
        hit = sum(1 for v in signals.values() if v)
        # Fixture inventory ok when pages walked; rich signals vary by demo.
        rows.append({
            "fixture": fixture,
            "signals": signals,
            "hit": hit,
            "of": len(SIGNALS),
            "ok": bool(signals.get("pages_walked")),
        })

    # Union coverage across fixtures
    union = {s: any(r["signals"].get(s) for r in rows) for s in SIGNALS}
    union_hit = sum(1 for v in union.values() if v)
    passed = sum(1 for r in rows if r.get("ok"))
    evidence = {
        "gate_a_complete": False,
        "drill": "discovery_surface_matrix",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "signal_keys": list(SIGNALS),
        "fixtures": rows,
        "union": union,
        "union_hit": union_hit,
        "union_of": len(SIGNALS),
        "passed": passed,
        "total": len(rows),
        "ok": passed == len(rows) and union_hit >= 6,
        "reason": (
            f"Discovery surface matrix fixtures={passed}/{len(rows)} "
            f"union={union_hit}/{len(SIGNALS)}; full Gate A live completeness still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (
        (Path(ops_dir) / "discovery_surface_matrix_drill.json")
        if ops_dir else EVIDENCE
    )
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "discovery_surface_matrix_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
