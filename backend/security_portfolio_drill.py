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


def run_security_portfolio_drill(*, ops_dir: Path | None = None) -> dict:
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
    dest = Path(ops_dir) if ops_dir else EVIDENCE.parent
    dest.mkdir(parents=True, exist_ok=True)
    out = (Path(ops_dir) / "security_portfolio_drill.json") if ops_dir else EVIDENCE
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if ops_dir is None:
        art = ROOT / "artifacts" / "ops" / "security_portfolio_drill.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return evidence
