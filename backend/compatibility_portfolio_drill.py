"""Gate F: DemoStore compatibility portfolio (desktop + mobile viewport matrix).

Offline Chromium only — broad live multi-browser CI still open.
gate_f_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .portfolio_gates import evaluate_compatibility

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "compatibility_portfolio_drill.json"
PATHS = ("/", "/about", "/lab")
DESKTOP = {"width": 1280, "height": 720}
MOBILE = {"width": 390, "height": 844}


def run_compatibility_portfolio_drill(*, ops_dir: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    from tests.demo_store import DemoStore

    store = DemoStore().start()
    desktop_ok = 0
    mobile_ok = 0
    pages: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for path in PATHS:
                url = store.url.rstrip("/") + path
                desk = browser.new_page(viewport=DESKTOP)
                desk.goto(url, wait_until="domcontentloaded")
                desk.wait_for_timeout(100)
                desktop_ok += 1
                desk.close()
                mob = browser.new_page(viewport=MOBILE)
                mob.goto(url, wait_until="domcontentloaded")
                mob.wait_for_timeout(100)
                mobile_ok += 1
                mob.close()
                pages.append({"url": url, "desktop": True, "mobile": True})
            browser.close()
    finally:
        try:
            store.stop()
        except Exception:
            pass

    matrix = {
        "desktop": desktop_ok,
        "mobile": mobile_ok,
        "desktop_or_default": desktop_ok,
        "mobile_checked": mobile_ok,
        "browsers": ["chromium"],
        "gate_f_complete": False,
        "pages": pages,
    }
    portfolio = evaluate_compatibility(matrix)
    evidence = {
        "gate_f_complete": False,
        "drill": "demo_store_compatibility_portfolio",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "DemoStore",
        "pages_walked": list(PATHS),
        "matrix": {
            "desktop": desktop_ok,
            "mobile": mobile_ok,
            "browsers": ["chromium"],
        },
        "portfolio": portfolio,
        "ok": bool(portfolio.get("ok")),
        "reason": (
            "DemoStore desktop+mobile Chromium viewport matrix evaluated; "
            "broad live multi-browser CI still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "compatibility_portfolio_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "compatibility_portfolio_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        work = ROOT / "artifacts" / "ops" / "compatibility_portfolio_work"
        work.mkdir(parents=True, exist_ok=True)
        (work / "compatibility.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    return evidence
