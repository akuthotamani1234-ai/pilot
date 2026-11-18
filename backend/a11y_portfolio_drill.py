"""Gate F: offline a11y portfolio evidence from DemoStore inventory.

Builds an a11y_page payload from a short Playwright walk and evaluates it.
Broad live CI still open — gate_f_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .portfolio_capture import capture_portfolios
from .portfolio_gates import evaluate_a11y

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "a11y_portfolio_drill.json"
PATHS = ("/", "/about", "/lab", "/signin")


def run_a11y_portfolio_drill(*, ops_dir: Path | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    from tests.demo_store import DemoStore

    store = DemoStore().start()
    pages: list[dict] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            for path in PATHS:
                page.goto(store.url.rstrip("/") + path, wait_until="domcontentloaded")
                page.wait_for_timeout(150)
                snap = page.evaluate(
                    """() => {
                      const images = [...document.querySelectorAll('img')].map(img => ({
                        src: img.getAttribute('src') || '',
                        alt: img.getAttribute('alt'),
                        missing_alt_attr: !img.hasAttribute('alt'),
                      }));
                      const inputs = [...document.querySelectorAll('input,select,textarea')].map(el => ({
                        name: el.getAttribute('name') || el.id || '',
                        label: (el.labels && el.labels[0] ? el.labels[0].innerText : '')
                          || el.getAttribute('aria-label') || '',
                        selector: el.id ? ('#' + el.id) : (el.name || el.tagName.toLowerCase()),
                      }));
                      return {images, inputs};
                    }"""
                )
                pages.append({
                    "url": store.url.rstrip("/") + path,
                    "imageAlts": snap.get("images") or [],
                    "inputs": snap.get("inputs") or [],
                })
            browser.close()
    finally:
        try:
            store.stop()
        except Exception:
            pass

    work = Path(ops_dir) if ops_dir else (ROOT / "artifacts" / "ops" / "a11y_portfolio_work")
    work.mkdir(parents=True, exist_ok=True)
    captured = capture_portfolios(work, pages, source_url=store.url)
    a11y_page = captured.get("a11y_page") or {}
    portfolio = evaluate_a11y(a11y_page)
    evidence = {
        "gate_f_complete": False,
        "drill": "demo_store_a11y_portfolio",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "DemoStore",
        "pages_walked": list(PATHS),
        "portfolio": portfolio,
        "ok": portfolio.get("verdict") != "unknown",
        "reason": (
            "DemoStore a11y portfolio evaluated from inventoried images/inputs; "
            "broad live multi-browser CI still open"
        ),
    }
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "a11y_portfolio_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "a11y_portfolio_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
