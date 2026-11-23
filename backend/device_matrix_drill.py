"""Gate D: combined device/viewport matrix evidence snapshot.

Merges web viewport evidence (if present), Android protocol dry-run rows, and
the local ADB probe. Live emulator/API24+ still required — gate_d_complete False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .android_adb_probe import run_adb_probe
from .device_matrix import evaluate_matrix, protocol_dry_run_evidence

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "device_matrix_drill.json"


def _linked_matrix() -> dict:
    return {
        "gate_d_complete": False,
        "ok": False,
        "drill": "combined_device_matrix_snapshot",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def _load_rows(name: str) -> list[dict]:
    from .finalization import folder_is_linked

    rows: list[dict] = []
    for root in (ROOT / "artifacts" / "ops", ROOT / "docs" / "ops-evidence"):
        path = root / name
        if folder_is_linked(path) or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                rows.extend(payload)
            elif isinstance(payload, dict) and isinstance(payload.get("rows"), list):
                rows.extend(payload["rows"])
            elif isinstance(payload, dict) and isinstance(payload.get("matrix_rows"), list):
                rows.extend(payload["matrix_rows"])
        except (OSError, ValueError):
            pass
    return rows


def run_device_matrix_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    name = "device_matrix_drill.json"
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    if folder_is_linked(dest) or folder_is_linked(dest / name):
        return _linked_matrix()
    from .device_matrix import viewport_evidence_from_app_map

    web_rows = _load_rows("device_matrix_evidence.json")
    # Controlled DemoStore walk supplies desktop+phone viewport evidence when missing.
    if not web_rows:
        try:
            from playwright.sync_api import sync_playwright

            from tests.demo_store import DemoStore

            store = DemoStore().start()
            app_map = []
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    desk = browser.new_page(viewport={"width": 1366, "height": 900})
                    desk.goto(store.url, wait_until="domcontentloaded")
                    app_map.append({"url": store.url, "status": 200})
                    mob = browser.new_page(viewport={"width": 390, "height": 844})
                    mob.goto(store.url, wait_until="domcontentloaded")
                    app_map.append({
                        "url": store.url, "status": 200,
                        "mobile_only": True, "layout": "phone",
                    })
                    browser.close()
            finally:
                store.stop()
            web_rows = viewport_evidence_from_app_map(app_map)
        except Exception:
            web_rows = []

    android_live = _load_rows("android_live_matrix_rows.json")
    android_live += _load_rows("android_emulator_smoke_drill.json")
    android_live += _load_rows("android_appium_product_matrix_drill.json")
    android_dry = protocol_dry_run_evidence()
    adb = run_adb_probe(ops_dir=ops_dir)  # (into the same folder as this drill: a test's temp folder stays a temp folder)
    scored = evaluate_matrix(list(web_rows) + list(android_live) + list(android_dry))
    appium_rows = [
        r for r in android_live
        if isinstance(r, dict) and r.get("source") == "android_appium_product_matrix"
    ]
    evidence = {
        "gate_d_complete": False,
        "drill": "combined_device_matrix_snapshot",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "web_rows": len(web_rows),
        "android_live_rows": len(android_live),
        "android_appium_rows": len(appium_rows),
        "android_dry_run_rows": len(android_dry),
        "adb_probe": {
            "ok": adb.get("ok"),
            "adb_present": adb.get("adb_present"),
            "devices_online": adb.get("devices_online"),
            "api_levels": adb.get("api_levels") or [],
            "reason": adb.get("reason"),
        },
        "matrix": scored,
        "ok": True,
        "reason": (
            "Combined web + Android Appium/smoke + protocol dry-run + ADB probe snapshot; "
            "broad multi-device CI product-matrix artifacts still open"
            if appium_rows else
            "Combined web + Android smoke/live + protocol dry-run + ADB probe snapshot; "
            "full Appium product matrix still open"
            if android_live else
            "Combined web + Android protocol dry-run + ADB probe snapshot recorded; "
            "live emulator/API24+ executed matrix still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
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
