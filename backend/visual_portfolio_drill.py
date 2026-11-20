"""Gate F: first-run visual portfolio evidence from DemoStore screenshots.

Captures screenshots, writes visual.json via visual_capture, and evaluates.
Broad live CI still open — gate_f_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .portfolio_gates import evaluate_visual
from .visual_capture import capture_visual

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "visual_portfolio_drill.json"
PATHS = ("/", "/about", "/lab")


def _linked_visual() -> dict:
    return {
        "gate_f_complete": False,
        "ok": False,
        "drill": "demo_store_visual_portfolio",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_visual_portfolio_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "visual_portfolio_drill.json"
    work = Path(ops_dir) / "visual_work" if ops_dir else (ROOT / "artifacts" / "ops" / "visual_portfolio_work")
    shots = work / "shots"
    if (folder_is_linked(dest) or folder_is_linked(dest / out_name) or folder_is_linked(work)
            or folder_is_linked(shots) or folder_is_linked(work / "visual.json")):
        return _linked_visual()

    from playwright.sync_api import sync_playwright

    from tests.demo_store import DemoStore

    store = DemoStore().start()
    shots.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            for i, path in enumerate(PATHS):
                page.goto(store.url.rstrip("/") + path, wait_until="domcontentloaded")
                page.wait_for_timeout(150)
                rel = f"shots/page_{i}.png"
                page.screenshot(path=str(work / rel), full_page=False)
                pages.append({
                    "url": store.url.rstrip("/") + path,
                    "slug": path.strip("/") or "home",
                    "screenshot": rel,
                })
            browser.close()
    finally:
        try:
            store.stop()
        except Exception:
            pass

    if folder_is_linked(work) or folder_is_linked(work / "visual.json"):
        return _linked_visual()
    report = capture_visual(work, pages)
    portfolio = evaluate_visual(report)
    evidence = {
        "gate_f_complete": False,
        "drill": "demo_store_visual_portfolio",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "DemoStore",
        "pages_walked": list(PATHS),
        "pages_recorded": len(report.get("pages") or []),
        "portfolio": portfolio,
        "ok": portfolio.get("verdict") != "unknown",
        "reason": (
            "DemoStore first-run visual evidence captured (pixel diff not run); "
            "broad live multi-browser CI still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_visual()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_visual()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
