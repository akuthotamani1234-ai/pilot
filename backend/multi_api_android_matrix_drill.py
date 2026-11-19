"""Gate D: multi-API Android matrix snapshot (API24 smoke + API30+ Appium).

Combines existing live evidence rows so both API tiers appear in one matrix
artifact. Broad multi-device CI runners still open — ``gate_d_complete`` False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .device_matrix import evaluate_matrix

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "multi_api_android_matrix_drill.json"


def _linked_matrix() -> dict:
    return {
        "gate_d_complete": False,
        "ok": False,
        "drill": "multi_api_android_matrix",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def _load(name: str) -> dict | list | None:
    from .finalization import folder_is_linked

    for root in (ROOT / "docs" / "ops-evidence", ROOT / "artifacts" / "ops"):
        path = root / name
        if folder_is_linked(path) or not path.is_file():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def run_multi_api_android_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    if ops_dir is not None and folder_is_linked(Path(ops_dir)):
        return _linked_matrix()

    rows: list[dict] = []
    sources: dict[str, bool] = {}

    # Prefer dedicated API24 smoke artifact; fall back to latest smoke only if API==24.
    api24 = _load("android_emulator_smoke_api24_drill.json")
    smoke = _load("android_emulator_smoke_drill.json")
    api24_src = None
    if isinstance(api24, dict) and bool(api24.get("ok")) and int(api24.get("api_level") or 0) == 24:
        api24_src = api24
    elif (
        isinstance(smoke, dict)
        and bool(smoke.get("ok"))
        and int(smoke.get("api_level") or 0) == 24
    ):
        api24_src = smoke
    if api24_src is not None:
        sources["api24_smoke"] = True
        for row in api24_src.get("matrix_rows") or []:
            if isinstance(row, dict):
                rows.append({**row, "api_tier": "api24_smoke"})
    else:
        sources["api24_smoke"] = False

    appium = _load("android_appium_product_matrix_drill.json")
    if isinstance(appium, dict):
        sources["api30_appium"] = bool(appium.get("ok")) and int(
            appium.get("api_level") or 0
        ) >= 26
        for row in appium.get("matrix_rows") or []:
            if isinstance(row, dict):
                rows.append({**row, "api_tier": "api30_appium"})

    live = _load("android_live_matrix_rows.json")
    if isinstance(live, list):
        for row in live:
            if isinstance(row, dict):
                rows.append(row)

    scored = evaluate_matrix(rows)
    api_levels = sorted({
        int(r["api_level"])
        for r in rows
        if isinstance(r, dict) and str(r.get("api_level") or "").isdigit()
    })
    evidence = {
        "gate_d_complete": False,
        "drill": "multi_api_android_matrix",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sources": sources,
        "api_levels": api_levels,
        "rows": len(rows),
        "matrix": scored,
        "android_profiles_verified": [
            p for p in (scored.get("verified") or []) if p.startswith("android.")
        ],
        "ok": bool(sources.get("api24_smoke")) and bool(sources.get("api30_appium")),
        "reason": (
            f"Multi-API Android matrix api_levels={api_levels} "
            f"(smoke={sources.get('api24_smoke')}, appium={sources.get('api30_appium')}); "
            "broad multi-device CI runners still open"
        ),
    }

    text = json.dumps(evidence, indent=2)
    name = "multi_api_android_matrix_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_matrix()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, name, text):
        return _linked_matrix()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, name, text)
    return evidence
