"""Gate F: passive security portfolio evidence from DemoStore (no probing).

Observes transport + response headers only. Never scans or exploits.
Broad live CI still open — gate_f_complete stays False.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .portfolio_gates import evaluate_security

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "ops-evidence" / "security_portfolio_drill.json"


def _linked_security() -> dict:
    return {
        "gate_f_complete": False,
        "ok": False,
        "drill": "demo_store_security_portfolio",
        "reason": "The ops folder is a link, so the drill was not saved.",
    }


def run_security_portfolio_drill(*, ops_dir: Path | None = None) -> dict:
    from .finalization import folder_is_linked, write_text_unless_linked

    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    out_name = "security_portfolio_drill.json"
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_security()

    from playwright.sync_api import sync_playwright

    from tests.demo_store import DemoStore

    store = DemoStore().start()
    headers: dict = {}
    https = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            resp = page.goto(store.url, wait_until="domcontentloaded")
            if resp is not None:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                https = str(resp.url or store.url).startswith("https://")
            else:
                https = store.url.startswith("https://")
            browser.close()
    finally:
        try:
            store.stop()
        except Exception:
            pass

    portfolio = evaluate_security(headers, https=https)
    evidence = {
        "gate_f_complete": False,
        "drill": "demo_store_security_portfolio",
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fixture": "DemoStore",
        "https": https,
        "headers_observed": sorted(headers.keys()),
        "portfolio": portfolio,
        "probe": False,
        "ok": portfolio.get("verdict") != "unknown",
        "reason": (
            "Passive DemoStore security observations recorded (no probing); "
            "broad live multi-browser CI still open"
        ),
    }
    text = json.dumps(evidence, indent=2)
    if folder_is_linked(dest) or folder_is_linked(dest / out_name):
        return _linked_security()
    dest.mkdir(parents=True, exist_ok=True)
    if not write_text_unless_linked(dest, out_name, text):
        return _linked_security()
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops"
        if not folder_is_linked(art) and not folder_is_linked(art / out_name):
            art.mkdir(parents=True, exist_ok=True)
            write_text_unless_linked(art, out_name, text)
    return evidence
