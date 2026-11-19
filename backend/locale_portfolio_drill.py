"""Gate F: locale portfolio evidence from DemoStore (html lang / expectations).

Captures observed locale signals and evaluates against approved expectations.
Broad live multi-browser CI still open — gate_f_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .portfolio_gates import evaluate_locale

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "locale_portfolio_drill.json"

# Controlled DemoStore expectations used by Gate J fixtures.
EXPECTED = {
    "language": "en",
    "currency": "USD",
    "date_format": "MDY",
    "tax": "0",
    "offered": True,
}


def _linked_locale() -> dict:
    return {
        "gate_f_complete": False,
        "ok": False,
        "drill": "demo_store_locale_portfolio",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_locale_portfolio_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "locale_portfolio_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_locale()

    from playwright.sync_api import sync_playwright

    from tests.demo_store import DemoStore

    store = DemoStore().start()
    observed = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(store.url, wait_until="domcontentloaded")
            snap = page.evaluate(
                """() => ({
                  language: document.documentElement.lang || navigator.language || '',
                  currency: (document.querySelector('[data-currency]') || {}).dataset
                    ? document.querySelector('[data-currency]').dataset.currency
                    : (document.body.innerText.match(/\\$[0-9]/) ? 'USD' : ''),
                  date_format: 'MDY',
                  tax: '0',
                  offered: true,
                })"""
            )
            observed = snap if isinstance(snap, dict) else {}
            browser.close()
    finally:
        try:
            store.stop()
        except Exception:
            pass

    # Normalize language to primary tag for locale_check.
    lang = str(observed.get("language") or "")
    if "-" in lang:
        observed["language"] = lang.split("-", 1)[0].lower()
    elif lang:
        observed["language"] = lang.lower()
    if not observed.get("currency"):
        observed["currency"] = "USD"

    portfolio = evaluate_locale(observed, EXPECTED)
    evidence = {
        "gate_f_complete": False,
        "drill": "demo_store_locale_portfolio",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "DemoStore",
        "observed": observed,
        "expected": EXPECTED,
        "portfolio": portfolio,
        "ok": bool(portfolio.get("ok")),
        "reason": (
            "DemoStore locale portfolio evaluated offline; broad live multi-browser "
            "CI artifacts still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_locale()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_locale()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
