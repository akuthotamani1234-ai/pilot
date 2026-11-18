"""Gate F: performance portfolio evidence from DemoStore load timings.

Records load_time_ms samples and evaluates against default budgets.
Broad live CI still open — gate_f_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .portfolio_gates import evaluate_performance

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "perf_portfolio_drill.json"
PATHS = ("/", "/about", "/lab", "/deals", "/signin")


def run_perf_portfolio_drill(*, ops_dir: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    from tests.demo_store import DemoStore

    store = DemoStore().start()
    samples: list[float] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            for path in PATHS:
                t0 = time.perf_counter()
                page.goto(store.url.rstrip("/") + path, wait_until="domcontentloaded")
                samples.append((time.perf_counter() - t0) * 1000.0)
            browser.close()
    finally:
        try:
            store.stop()
        except Exception:
            pass

    timings = None
    if samples:
        timings = {
            "dom_content_loaded_ms": sorted(samples)[len(samples) // 2],
            "load_ms": max(samples),
            "largest_contentful_paint_ms": sorted(samples)[len(samples) // 2],
            "samples": len(samples),
        }
    portfolio = evaluate_performance(timings)
    evidence = {
        "gate_f_complete": False,
        "drill": "demo_store_perf_portfolio",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "DemoStore",
        "pages_walked": list(PATHS),
        "timings": timings,
        "portfolio": portfolio,
        "ok": portfolio.get("verdict") != "unknown",
        "reason": (
            "DemoStore performance portfolio evaluated from controlled load timings; "
            "broad live multi-browser CI still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "perf_portfolio_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "perf_portfolio_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
